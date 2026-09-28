# app — FastAPI backend package

The entire API lives here: HTTP edge, persistence, GitHub/LLM/sandbox
services, and the durable review pipelines. Async end-to-end; Postgres
is the only persistence tier (DBOS shares it).

## Layout

- `core/` — cross-cutting foundation: settings, DB engine, auth session,
  middleware, WorkOS client, telemetry. No domain logic.
- `models/` — SQLModel tables + enums. Source of truth for the schema;
  Alembic mirrors it.
- `repositories/` — generic `BaseRepository[T]` plus one thin subclass
  per table. Callers that touch the DB take an `AsyncSession`.
- `routers/` — HTTP edge. Validation + dispatch only; durable work is
  handed to DBOS workflows, never done inline.
- `services/` — domain services behind the §9 contract: ctx objects,
  errors as values, no logging. (`agent_v2`, `github`, `llm`,
  `sandbox`.)
- `workflows/` — DBOS durable pipelines (`review_v2`,
  `repair_and_publish`) plus the webhook `triggers/` adapters.
- `utils/` — shared value types (`branded`), sandbox path layout
  (`util`), agent output schemas (`schema`), misc helpers.

## Request flow

```
router (validate + dispatch) → trigger adapter (resolve user/repo)
  → DBOS workflow (checkpointed steps) → service (pure call + value error)
  → repository (AsyncSession) → Postgres
```

## Notes

- Auth is opt-in per route group: `core/middleware.py::PROTECTED_PREFIXES`.
  The only anonymous I/O surface is the HMAC-verified webhook receiver.
- Workflow ids are deterministic and encode the domain
  (`review-v2:{repo_id}:{pr}:{head_sha[:7]}`), so duplicate deliveries
  dedupe and restarts are safe.
