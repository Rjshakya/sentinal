# review_v2/steps — one worker per pipeline phase

Worker library consumed by the `durable/` handlers (one thin `@durable_step`
per worker: validate input model, `asyncio.run` the worker, return
`model_dump`). Only the sandbox id travels between steps; every step
reconnects. In pipeline order:

## Steps

- `create_sandbox.py` — fresh ephemeral sandbox for the run.
- `clone_repo_v2.py` — default-branch clone + PR-ref fetch +
  detached head checkout, verify-gated. Fail-closed.
- `codegraph_index.py` — `pip install sentinel-codegraph` + index
  of the PR-head tree. Fail-closed (pin/timeouts in-file).
- `upsert_pr.py` — insert/update the `PullRequest` row.
- `review_lifecycle.py` — `review` row `RUNNING → SUCCESS/FAILED`
  transitions.
- `fetch_diff.py` — `git diff {base|diffBaseSha}...head` into the
  sandbox (`diffBaseSha` narrows incremental re-reviews).
- `split_diff.py` — upload + run the splitter script, parse its
  stdout summary (`_helpers.py` holds shared path/connect helpers).
- `list_chunks.py` — inventory `splitted_diffs/` into the diff
  truth (`ChunkInventory`).
- `invoke_planner.py` — planning agent + `plan.json` read-back
  (enrichment-only: failure degrades to empty context).
- `invoke_file.py` — one scoped per-file lane per job, batched;
  each file retries alone, failures degrade to nothing.
- `combine.py` — pure joins (trivial filter, inventory ⋈ planner
  context, batching, `verdictFor`). No I/O.
- `extract_result.py` — transcribe agent text into comment drafts
  (structured extractor).
- `synthesize_summary.py` — walkthrough summary (degrades to
  empty, never fails the run).
- `persist.py` — summary / comments / usage rows.
- `post_review.py` — best-effort inline GitHub post (terminal 4xx →
  `posted=False`, which dispatches the repair durable) + back-link
  updates.
- `kill_sandbox.py` — destroy the ephemeral sandbox; never masks
  the outcome.

## Notes

- `__init__.py` re-exports every worker plus the pure helpers.
- Workers raise `ReviewStepFailure` / `TransientReviewStepFailure`;
  the durable step retries transient failures per its `StepConfig`.
