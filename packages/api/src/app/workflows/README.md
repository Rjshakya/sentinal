# workflows — durable pipelines + webhook adapters

Every long-running unit of work is a durable execution: each I/O step
is checkpointed, transient failures retry per-step, and restarts
resume instead of re-running.

## Layout

- `triggers/` — webhook-edge adapters. Pure payload extraction plus one
  best-effort Invoke per delivery (`invoke.py` for review, `repair.py`
  for the repair follow-up). See its README.
- `durable/` — the durable handlers (`opened_handler.py`,
  `comment_handler.py`, `repair_handler.py`), the shared
  `pipeline.py` / `repair_pipeline.py` agent phases, and the dispatch
  helper `invoke.py`. Checkpointed `@durable_step`s invoke the
  `review_v2/steps/` workers. Ids
  `review-v2:{gh_repo}:{pr}:{head_sha[:7]}` and `repair:{pr}:{head_sha[:7]}`.
- `review_v2/` — the PR review worker library: sandbox/LLM/agent
  workers consumed by the `durable/` handlers, plus the workflow input/result
  types and the error hierarchy.

## Notes

- Routers only validate + dispatch; triggers only adapt + dispatch.
  All domain logic lives in the workflow steps and services.
- Deterministic ids dedupe duplicate deliveries (same head SHA =
  same review execution; same commit = same repair execution).
- When the review post returns `posted=False` with comments to show,
  the pipeline dispatches the repair durable best-effort.
