# app — FastAPI backend package

The entire API lives here: HTTP edge, persistence, GitHub/LLM/sandbox
services, and the durable review pipelines. Async end-to-end; Postgres
is the only persistence tier.

## Layout

- `core/` — cross-cutting foundation: settings, DB engine, auth session,
  middleware, WorkOS client, telemetry. No domain logic.
- `models/` — SQLModel tables + enums. Source of truth for the schema;
  Alembic mirrors it.
- `repositories/` — generic `BaseRepository[T]` plus one thin subclass
  per table. Callers that touch the DB take an `AsyncSession`.
- `routers/` — HTTP edge. Validation + dispatch only; durable work is
  handed to durable executions, never done inline.
- `services/` — domain services behind the §9 contract: ctx objects,
  errors as values, no logging. (`agent_v2`, `github`, `llm`,
  `sandbox`.)
- `workflows/` — durable pipelines (`durable/` handlers + pipelines
  (`invoke.py`), `review_v2/` worker library) plus the webhook
  `triggers/` adapters. Workers live in `review_v2/steps/`.
- `utils/` — shared value types (`branded`), sandbox path layout
  (`util`), agent output schemas (`schema`), misc helpers.

## Request flow

```
router (validate + dispatch) → trigger adapter (pure extraction +
  boto3 Invoke, no DB — ctx resolves inside the handler)
  → durable execution (checkpointed steps) → service (pure call + value error)
  → repository (AsyncSession) → Postgres
```

## Notes

- Auth is opt-in per route group: `core/middleware.py::PROTECTED_PREFIXES`.
  The only anonymous I/O surface is the HMAC-verified webhook receiver.
- Workflow ids are deterministic and encode the domain
  (`review-v2:{gh_repo}:{pr}:{head_sha[:7]}` for opened reviews,
  delivery-suffixed for comment re-reviews, `repair:{pr}:{head_sha[:7]}`
  for repairs), so duplicate deliveries dedupe and restarts are safe.
  The `DurableExecutionName` on the wire is the dash-sanitized form
  (AWS charset rules); the `review.workflow_id` column keeps colons.
