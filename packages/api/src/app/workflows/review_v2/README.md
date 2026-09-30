# review_v2 — planner + per-file-agent review worker library

Webhook → ephemeral sandbox → clone at head → index graph →
planner + file agents → persist + post inline. One run = one PR
head SHA; the id `review-v2:{repo}:{pr}:{sha7}` dedupes duplicate
deliveries to the same durable execution.

## Mental model

```
clone (one world: PR tree) → index (map of that world)
  → chunks (WHAT changed — the diff truth)
  → graph (WHERE it lives — the repo truth)
  → planner (context) + file agents (findings)
  → extract → persist / post
```

Two truths, never invented by an LLM: chunks own line numbers
(`splitted_diffs/`, observed via grep, never recomputed), the
graph owns structure (callers/callees/imports). Agents read both;
the host decides which files get reviewed.

## Layout

- `steps/` — one worker per phase (sandbox, clone, graph-index,
  diff, split, chunks, planner, file, extract, persist, post,
  lifecycle). Only the sandbox id travels; every step reconnects.
  See its README. The durable checkpoint edges live in
  `durable/steps/`.
- `steps/combine.py` — pure joins between steps (trivial filter,
  inventory ⋈ planner context, batching, `verdictFor`). No I/O.
- `types.py` — serializable contract (`ReviewWorkflowInput`,
  `RepoSnapshot`, usages, limits).
- `errors.py` — error values + step exceptions + retry classifiers.
- `scripts/` — uploaded as bytes, never imported on the host.

## Notes

- **Infra is fail-closed**: clone → graph-index → diff/split
  either succeed or fail the run. No half-built reviews.
- **Agents degrade, never fail the run**: planner failure →
  empty context (files still reviewed); file lanes retry alone
  and drop to nothing. Only "planner degraded AND every lane
  failed" fails the run.
- When the inline post returns `posted=False`, the pipeline
  dispatches the repair durable (`durable/repair_pipeline.py`),
  which re-anchors and publishes the saved review.
