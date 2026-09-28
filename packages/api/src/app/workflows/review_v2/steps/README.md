# review_v2/steps — one I/O boundary per step

Each file wraps a single external interaction (sandbox, clone,
GitHub, DB, LLM) as a pure worker plus its DBOS step. Only the
sandbox id travels between steps; every step reconnects. In
pipeline order:

## Steps

- `get_repo.py` — `getRepo` (pure) / `getRepoTx`: local `Repo` row.
- `create_sandbox.py` — fresh ephemeral sandbox for the run.
- `clone_repo_v2.py` — default-branch clone + PR-ref fetch +
  detached head checkout, verify-gated. Fail-closed.
- `codegraph_index.py` — `pip install sentinel-codegraph` + index
  of the PR-head tree. Fail-closed (pin/timeouts in-file).
- `upsert_pr.py` — insert/update the `PullRequest` row.
- `review_lifecycle.py` — `review` row `RUNNING → SUCCESS/FAILED`
  transitions (+ `buildErrorContext`).
- `fetch_diff.py` — `git diff {base|diffBaseSha}...head` into the
  sandbox (`diffBaseSha` narrows incremental re-reviews).
- `split_diff.py` — upload + run the splitter script, parse its
  stdout summary (`_helpers.py` holds shared path helpers).
- `list_chunks.py` — inventory `splitted_diffs/` into the diff
  truth (`ChunkInventory`).
- `invoke_planner.py` — planning agent + `plan.json` read-back
  (enrichment-only: failure degrades to empty context).
- `invoke_file.py` — one scoped per-file lane per job, batched;
  each file retries alone, failures degrade to nothing.
- `combine.py` — pure joins (trivial filter, inventory ⋈ planner
  context, batching, `verdictFor`). No I/O, no DBOS.
- `extract_result.py` — transcribe agent text into comment drafts
  (structured extractor).
- `synthesize_summary.py` — walkthrough summary (degrades to
  empty, never fails the run).
- `persist.py` — summary / comments / usage rows.
- `post_review.py` — best-effort inline GitHub post (own retry
  policy; terminal 4xx → `posted=False`) + back-link updates.
- `kill_sandbox.py` — always in `finally`; never masks the outcome.

## Notes

- `__init__.py` re-exports every step plus the pure helpers, so
  `workflow.py` reads as the pipeline order.
