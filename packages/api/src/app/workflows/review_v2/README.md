# review_v2 — planner + per-file-agent review workflow

Isolated successor of `workflows/review`: same infra, new agent phase.
Not wired to any webhook trigger (no swap); v1 keeps serving traffic.
Workflow ids live in the `review-v2:` namespace so eval runs can never
collide with production v1 runs.

## Intent

- `splitted_diffs/` is the diff truth. The host inventories it
  (`listChunkFilesStep`) and fans out over it — no LLM ever decides
  which files get reviewed.
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
│                    # FileLaneError, V2AgentsError). Raised wrappers
│                    # (ReviewStepFailure/Transient) + shouldRetry are
│                    # REUSED from workflows/review/errors — not duplicated.
├── workflow.py      # reviewWorkflowV2 orchestrator + createReviewV2WorkflowId
│                    # + fixed planner/file call-limit helpers. Straight-line:
│                    # infra (imported from v1 steps) → v2 agent phase below →
│                    # persist/post/lifecycle (imported from v1 steps).
└── steps/
    ├── __init__.py      # Re-exports the v2 steps + pure helpers.
    ├── list_chunks.py   # I/O boundary #1: `grep '^### '` in sandbox →
    │                    # ChunkInventory. Owns connectV2Sandbox (local
    │                    # reconnect helper; v1's is package-private).
    ├── invoke_planner.py# I/O boundary #2: planner research
    │                    # (invokePlannerStep → raw text+usage) + structured
    │                    # transcription (extractPlanStep → PlannerContext).
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
(`create_sandbox`, `clone_repo`, `fetch_diff`, `split_diff`,
`persist_*`, `post_review`, `review_lifecycle`, `extractCommentsStep`
all come from `workflows/review/steps`). Only the agent phase is new.
That's what makes the future swap a trigger-line change rather than
a migration.

## What's done

- `workflow.py` — `reviewWorkflowV2`: infra steps reused by import
  (sandbox, clone, diff, split, persist, post, lifecycle), then
  list-chunks → planner → join → batched fan-out → merge → extract →
  persist/post. Same `RUNNING`/`SUCCESS`/`FAILED` lifecycle, same
  `ReviewWorkflowCtx`/`ReviewWorkflowInput`/`ReviewRunResult` shapes.
- `steps/list_chunks.py` — `grep '^### '` over chunk headers →
  `ChunkInventory` (paths only; diff text never leaves the sandbox).
- `steps/invoke_planner.py` — planner research + structured
  `PlannerContext` extraction (same extractor model as v1).
- `steps/invoke_file.py` — one scoped file lane → `(raw_text, usage)`.
- `steps/combine.py` — pure: host-side trivial filter
  (`isTrivialFile`), context join (`buildFileReviewJobs`),
  report concat, batching, usage aggregation (`combineV2Reports`).
  The v2 base build is comments-only (empty summary).
- `errors.py` — `ChunkListError`, `PlannerStepError{research,extract}`,
  `FileLaneError{file}`, `V2AgentsError`. Raised step exceptions and
  retry predicates reused from v1.
- Verified: compiles, all modules import, pyright 0 errors/warnings,
  pure join/merge logic sanity-checked (repo test suite untouched —
  some of its tests are broken).

## What's left

- Real prompts (see `services/agent_v2` README) — the pipeline runs
  end-to-end today but agents carry placeholder instructions.
- Eval comparison vs v1 (judge F1/FP) on the same datasets, then the
  trigger swap (explicit future step, out of scope here).
- Possible follow-ups, only if evals demand: per-file extractor
  fallback when the concatenated report strains extractor context;
  cheaper planner/extractor models; a walkthrough summary derived
  from `PlannerContext` + findings.
