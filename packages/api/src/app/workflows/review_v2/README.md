# review_v2 — planner + per-file-agent review workflow

Webhook → ephemeral sandbox → clone at head → index graph →
planner + file agents → persist + post inline.

One run = one PR head SHA. The workflow id
`review-v2:{repo}:{pr}:{sha7}` is the idempotency key: duplicate
deliveries dedupe to the same DBOS workflow.

## Mental model

```
clone (one world: PR tree) → index (map of that world)
  → chunks (WHAT changed — the diff truth)
  → graph (WHERE it lives — the repo truth)
  → planner (context) + file agents (findings)
  → extract → persist / post
```

Two truths, never invented by an LLM: chunks own line numbers
(`splitted_diffs/`, observed via `grep -H`, never recomputed), the
graph owns structure (callers/callees/imports). Agents read both;
the host decides which files get reviewed.

## Infra: fail-closed

Clone → graph-index → diff/split either succeed or fail the run.
No half-built reviews — a degraded tree would force prompts to hedge
both worlds and breed Heisenbugs.

- **Clone** leaves the tree checked out at the head SHA (PR-ref fetch
  + detached checkout, verify-gated). Any refusal fails the run.
- **Graph** installs `sentinel-codegraph` and indexes the PR-head
  tree into the fixed run DB both the step and the tool recompute.
  Details (pin, timeouts, exit codes, `--overwrite` retry rule) live
  in `steps/codegraph_index.py::CODEGRAPH_PIN` — this README doesn't
  duplicate them. A dead graph fails the run; agents never review
  without their search tool.

## Agents: degrade, never fail the run

- **Planner is enrichment-only.** It maps the PR graph-first
  (`files → search → callers/callees`) and annotates files with
  context. Failure degrades to an empty `PlannerContext` — the files
  are still reviewed.
- **File lanes are N-wide, batched.** One scoped agent per chunk,
  each retrying alone; failures drop to nothing. Only "planner
  degraded AND every lane failed" becomes `V2AgentsError`.
- **Tool rule:** planner goes graph-first and cites node ids; each
  file agent checks blast radius (`callers`/`callees` on its changed
  symbols) before reading. Verb ladder lives in one place:
  `agent_v2/prompts/shared.py::SEARCH_CODEGRAPH_TOOL_DESCRIPTION`.

## Layout

- `workflow.py` — the order. Straight-line: infra → agents → persist/post.
- `steps/` — one I/O boundary each (sandbox, clone, graph-index,
  diff, split, chunks, planner, file, extract, persist, post,
  lifecycle). Only the sandbox id travels; every step reconnects.
- `steps/combine.py` — pure joins between steps (trivial filter,
  inventory ⋈ planner context, batching, merge). No I/O, no DBOS.
- `errors.py` — error *values*, never raised; `shouldRetry`
  discriminates transient vs final at the step edge.
- `scripts/` — uploaded as bytes, never imported on the host.

## What's left

- Live sandbox proof of install → index → tool query.
- Template-bake the CLI to kill the per-run pip cost.
