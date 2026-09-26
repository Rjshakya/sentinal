# workflows — DBOS durable pipelines + webhook adapters

Every long-running unit of work is a DBOS workflow: each I/O step
is checkpointed, transient failures retry per-step, and restarts
resume instead of re-running. `__init__.py` documents the
types/errors/workflow/steps layout shared by all pipelines.

## Layout

- `triggers/` — webhook-edge adapters. Validate the delivery,
  resolve user/repo, and dispatch a workflow under a deterministic
  id. See its README.
- `review_v2/` — the PR review pipeline: ephemeral sandbox →
  clone → codegraph index → planner + per-file agents → persist +
  inline GitHub post. Id `review-v2:{repo_id}:{pr}:{head_sha[:7]}`.
- `repair_and_publish/` — follow-up pipeline that repairs an
  unpublished review draft and publishes it. Id
  `repair:{pr}:{commit}:{rand7}:publish`.

## Notes

- Routers only validate + dispatch; triggers only adapt + dispatch.
  All domain logic lives in the workflow steps and services.
- Deterministic ids dedupe duplicate deliveries (same head SHA =
  same workflow).
