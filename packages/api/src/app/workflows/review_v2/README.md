# review_v2 — planner + per-file-agent review workflow

Webhook → ephemeral sandbox → clone at head → index graph →
planner + file agents → persist + post inline. One run = one PR
head SHA; the id `review-v2:{repo}:{pr}:{sha7}` dedupes duplicate
deliveries to the same DBOS workflow.

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

- `workflow.py` — the order: infra → agents → persist/post.
- `steps/` — one I/O boundary each (sandbox, clone, graph-index,
  diff, split, chunks, planner, file, extract, persist, post,
  lifecycle). Only the sandbox id travels; every step reconnects.
  See its README.
- `steps/combine.py` — pure joins between steps (trivial filter,
  inventory ⋈ planner context, batching, `verdictFor`). No I/O.
- `types.py` — DBOS-serializable contract (`ReviewWorkflowCtx`,
  `ReviewWorkflowInput`, usages, limits).
- `errors.py` — error values + `shouldRetry` (transient vs final).
- `scripts/` — uploaded as bytes, never imported on the host.

## Notes

- **Infra is fail-closed**: clone → graph-index → diff/split
  either succeed or fail the run. No half-built reviews.
- **Agents degrade, never fail the run**: planner failure →
  empty context (files still reviewed); file lanes retry alone
  and drop to nothing. Only "planner degraded AND every lane
  failed" becomes `V2AgentsError`.
- Left: live sandbox proof of install → index → tool query;
  template-bake the CLI to kill the per-run pip cost.
