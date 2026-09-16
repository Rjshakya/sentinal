# review_v2 — planner + per-file-agent review workflow

The review pipeline: planner + per-file agents over shared infra
steps (sandbox, clone, diff, split, persist, post, lifecycle — all
owned by this package).

## Intent

- `splitted_diffs/` is the diff truth. The host inventories it
  (`listChunkFilesStep`) and fans out over it — no LLM ever decides
  which files get reviewed.
- Every job carries **two paths**: `filePath` (the real code path —
  what finding blocks cite) and `diffPath` (the exact on-disk `.md`
  chunk file, *observed* via `grep -H`, never recomputed). The file
  agent is told to open its chunk first and copy every anchor from
  its gutter columns — the repo copy is context only, never a
  line-number source. Killing the old dotted-name recompute removes
  the collision class (`a/b.c` vs `a.b/c` → one chunk) by
  construction.
- The v2 clone (`cloneRepoV2Step`) leaves the working tree checked
  out at the reviewed head SHA — clone + PR-ref fetch + detached
  checkout in one atomic script. Fail-closed: any checkout refusal
  fails the run instead of reviewing a half-built tree. Past the
  clone step there is exactly one world: PR tree + PR diff.
- The planner is **enrichment-only**: it annotates files with context.
  A planner miss costs context, never a review (the file is still
  reviewed with an empty slice). Planner failure degrades to an empty
  `PlannerContext`, never fails the run.
- Per-file agents run in sequential batches (`V2_FANOUT_BATCH_SIZE`); each file retries alone; failed files
  degrade to nothing. Surviving reports are concatenated and
  transcribed once by the shared comments extractor.

## Layout

```
workflows/review_v2/
├── __init__.py      # Public surface: types + errors + workflow.
├── README.md        # This file.
├── types.py         # The serializable contract: ReviewWorkflowCtx /
│                    # ReviewWorkflowInput / RepoSnapshot / ReviewRunResult /
│                    # usage envelopes. Ids are branded types.
├── errors.py        # Error VALUES (ReviewStepError subclasses:
│                    # ChunkListError, PlannerStepError, FileLaneError,
│                    # CloneV2Error/CloneV2TransientError,
│                    # CheckoutError/CheckoutTransientError,
│                    # V2AgentsError, + the shared infra values) and the
│                    # raised wrappers (ReviewStepFailure/Transient) +
│                    # shouldRetry and the transient classifiers.
├── workflow.py      # reviewWorkflowV2 orchestrator +
│                    # createReviewV2WorkflowId + buildReviewWorkflowInput
│                    # + fixed planner/file call-limit helpers. Straight-line:
│                    # infra → agent phase below → persist/post/lifecycle.
├── scripts/
│   └── split_diff.py# In-sandbox splitter (stdlib-only, uploaded as
│                    # bytes, never imported on the host).
└── steps/
    ├── __init__.py      # Re-exports every step + pure helper.
    ├── _helpers.py      # Shared pure helpers (sandbox reconnect,
    │                    # in-sandbox paths, output truncation).
    ├── create_sandbox.py# Per-run ephemeral sandbox.
    ├── clone_repo_v2.py # V2-native clone (I/O boundary #0):
    │                    # default-branch clone + PR-ref fetch +
    │                    # detached head checkout in ONE atomic
    │                    # in-sandbox script, verify-gated.
    │                    # Fail-closed: checkout refusal fails the run.
    ├── fetch_diff.py    # git diff into the sandbox.
    ├── split_diff.py    # Upload + run the split script.
    ├── get_repo.py      # Local repos-row lookup.
    ├── upsert_pr.py     # pull_requests row upsert.
    ├── review_lifecycle.py # review lifecycle-row transitions +
    │                    # buildErrorContext.
    ├── extract_result.py# Structured extractor steps
    │                    # (extractCommentsStep / extractSummaryStep).
    ├── persist.py       # Summary / comments / usage rows.
    ├── post_review.py   # Inline GitHub post + back-links.
    ├── kill_sandbox.py  # Best-effort sandbox destroy (finally).
    ├── list_chunks.py   # I/O boundary #1: `grep '^### '` in sandbox →
    │                    # ChunkInventory. Owns connectV2Sandbox (local
    │                    # reconnect helper).
    ├── invoke_planner.py# I/O boundary #2: planner research
    │                    # (invokePlannerStep → raw text+usage) + structured
    │                    # transcription (getPlanStep reads plan.json →
    │                    # PlannerContext, no LLM call).
    ├── invoke_file.py   # I/O boundary #3 (N-wide): one scoped file lane →
    │                    # (raw findings report + usage). Retried per file.
    ├── synthesize_summary.py # Walkthrough summary synthesis
    │                    # (degrades to empty, never fails the run).
    └── combine.py       # NO I/O, NO DBOS — pure functions the workflow calls
                         # between steps: isTrivialFile → buildFileReviewJobs
                         # (inventory ⋈ planner context) → chunkedJobs
                         # (batches of `V2_FANOUT_BATCH_SIZE`) → concatFileReports →
                         # coerceFileLaneError / combineV2Reports
                         # (merged review + token envelope) over the
                         # local CombinedReview / combineReviewResults /
                         # verdictFor merge rules.
```

## Clone contract (`cloneRepoV2Step`)

One atomic in-sandbox script: default-branch clone → PR-ref fetch
(`refs/pull/{pr}/head`, fork-safe — the head branch name is never
trusted) → `cat-file -e` gate → `checkout --detach {headSha}` →
`rev-parse HEAD` verify. Fail-closed per stage:

| Stage fails | Outcome |
|---|---|
| `git clone` | Fatal — no repo, nothing to review |
| PR-ref fetch | Fatal *only if* it makes checkout impossible (SHA gate); flag recorded for logs |
| `checkout --detach` / verify gate | **Fatal** — run ERROR, no partial-truth review |
| Runner dropout / timeout | Transient — DBOS retries ×3 |

Deliberately **no degrade-and-continue**: a degraded tree (base code
under a PR diff) would force prompts to hedge both worlds, split
evals by invisible state, and breed Heisenbugs. Past the clone step
there is exactly one world — PR tree + PR diff — so prompts assert
PR-state reads unconditionally. Chunks remain the sole anchor truth
for line numbers regardless.

## What's done

- `workflow.py` — `reviewWorkflowV2`: v2 clone (tree at head, verified)
  → upsert PR → `RUNNING` → fetch/split diff → list-chunks → planner
  → join → batched fan-out → merge → extract → persist/post. Same
  `RUNNING`/`SUCCESS`/`FAILED` lifecycle, same
  `ReviewWorkflowCtx`/`ReviewWorkflowInput`/`ReviewRunResult` shapes.
- `steps/list_chunks.py` — `grep -H '^### '` over chunk headers →
  `ChunkInventory` (real paths + exact on-disk diff file per chunk;
  diff text never leaves the sandbox).
- `steps/invoke_planner.py` — planner research (the agent submits
  via the `submit_plan` tool into the sandbox working dir's
  `plan.json`) + `getPlanStep` (reads the file back into a
  `PlannerContext`, no LLM call).
- `steps/invoke_file.py` — one scoped file lane → `(raw_text, usage)`.
- `steps/combine.py` — pure: host-side trivial filter
  (`isTrivialFile`), context join (`buildFileReviewJobs`, fills
  `filePath` + observed `diffPath` on every job), report concat,
  batching, usage aggregation (`combineV2Reports`).
- Dispatched by the webhook triggers
  (`workflows/triggers/review.py`) and the eval `POST /review`
  route; workflow ids live in the `review-v2:` namespace.

## What's left

- Possible follow-ups, only if evals demand: per-file extractor
  fallback when the concatenated report strains extractor context;
  cheaper planner/extractor models; a walkthrough summary derived
  from `PlannerContext` + findings.
