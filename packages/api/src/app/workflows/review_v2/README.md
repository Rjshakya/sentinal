# review_v2 — planner + per-file-agent review workflow

Isolated successor of `workflows/review`: same infra, new agent phase.
Not wired to any webhook trigger (no swap); v1 keeps serving traffic.
Workflow ids live in the `review-v2:` namespace so eval runs can never
collide with production v1 runs.

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
- Per-file agents run in sequential batches of 10
  (`V2_FANOUT_BATCH_SIZE`); each file retries alone; failed files
  degrade to nothing. Surviving reports are concatenated and
  transcribed once by the shared comments extractor.

## Layout

```
workflows/review_v2/
├── __init__.py      # Public surface: workflow + v2 errors only.
├── README.md        # This file.
├── errors.py        # V2 error VALUES (ChunkListError, PlannerStepError,
│                    # FileLaneError, CloneV2Error/CloneV2TransientError,
│                    # CheckoutError/CheckoutTransientError, V2AgentsError).
│                    # Raised wrappers (ReviewStepFailure/Transient) +
│                    # shouldRetry are REUSED from workflows/review/errors —
│                    # not duplicated.
├── workflow.py      # reviewWorkflowV2 orchestrator + createReviewV2WorkflowId
│                    # + fixed planner/file call-limit helpers. Straight-line:
│                    # infra (imported from v1 steps) → v2 agent phase below →
│                    # persist/post/lifecycle (imported from v1 steps).
└── steps/
    ├── __init__.py      # Re-exports the v2 steps + pure helpers.
    ├── clone_repo_v2.py # V2-native clone (I/O boundary #0): default-branch
    │                    # clone + PR-ref fetch + detached head checkout in
    │                    # ONE atomic in-sandbox script, verify-gated.
    │                    # Fail-closed: checkout refusal fails the run.
    ├── list_chunks.py   # I/O boundary #1: `grep '^### '` in sandbox →
    │                    # ChunkInventory. Owns connectV2Sandbox (local
    │                    # reconnect helper; v1's is package-private).
    ├── invoke_planner.py# I/O boundary #2: planner research
    │                    # (invokePlannerStep → raw text+usage) + structured
    │                    # transcription (getPlanStep reads plan.json →
  │                    # PlannerContext, no LLM call).
    ├── invoke_file.py   # I/O boundary #3 (N-wide): one scoped file lane →
    │                    # (raw findings report + usage). Retried per file.
    └── combine.py       # NO I/O, NO DBOS — pure functions the workflow calls
                         # between steps: isTrivialFile → buildFileReviewJobs
                         # (inventory ⋈ planner context) → chunkedJobs
                         # (batches of 10) → concatFileReports →
                         # coerceFileLaneError / combineV2Reports
                         # (merged review + token envelope).
```

The key structural rule: **infra steps are imported, never copied**
(`create_sandbox`, `fetch_diff`, `split_diff`, `persist_*`,
`post_review`, `review_lifecycle`, `extractCommentsStep` all come
from `workflows/review/steps`). The clone is the one deliberate
exception — v2 owns `clone_repo_v2.py` because the tree-at-head
invariant is a v2 requirement the shared v1 clone must never adopt
unilaterally. That's what makes the future swap a trigger-line change
rather than a migration.

## Clone contract (`cloneRepoV2Step`)

One atomic in-sandbox script: default-branch clone → PR-ref fetch
(`refs/pull/{pr}/head`, fork-safe — the head branch name is never
trusted) → `cat-file -e` gate → `checkout --detach {headSha}` →
`rev-parse HEAD` verify. Fail-closed per stage:

| Stage fails | Outcome |
|---|---|
| `git clone` | Fatal — no repo, nothing to review (as v1) |
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
  The v2 base build is comments-only (empty summary).
- `errors.py` — `ChunkListError`, `PlannerStepError{research,extract}`,
  `FileLaneError{file}`, `CloneV2Error`/`CloneV2TransientError`,
  `CheckoutError`/`CheckoutTransientError` (checkout refusal is final),
  `V2AgentsError`. Raised step exceptions and retry predicates reused
  from v1.
- Verified: compiles, all modules import, pyright 0 errors/warnings,
  pure join/merge logic + clone-summary parser + fail-closed worker
  mapping sanity-checked (repo test suite untouched — some of its
  tests are broken).

## What's left

- Real prompts (see `services/agent_v2` README) — the pipeline runs
  end-to-end today but agents carry placeholder instructions.
- Eval comparison vs v1 (judge F1/FP) on the same datasets, then the
  trigger swap (explicit future step, out of scope here).
- Possible follow-ups, only if evals demand: per-file extractor
  fallback when the concatenated report strains extractor context;
  cheaper planner/extractor models; a walkthrough summary derived
  from `PlannerContext` + findings.
