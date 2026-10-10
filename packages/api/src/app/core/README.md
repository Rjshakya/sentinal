# core — cross-cutting foundation

Settings, database wiring, auth, and process-wide clients. No domain
logic lives here; every other package imports from `core`, never the
reverse.

## Layout

- `config.py` — `Settings(BaseSettings)` loaded from the monorepo-root
  `.env`, plus the `settings` singleton. Groups: server, WorkOS,
  sandbox, LLM (`llm_model` as a `"provider:model"` string),
  GitHub App, durable function names, webhook secret, Langfuse
  (`LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY` / `LANGFUSE_BASE_URL`).
  `*_configured` properties are the 503 gates for routes.
- `db.py` — async engine + `async_session_maker`, the `get_session`
  FastAPI dependency, and `create_db_and_tables` (greenfield-dev
  convenience; Alembic owns real schema changes).
- `auth.py` — `Session` model + `get_current_session`: reads the
  sealed cookie, authenticates locally (no network IO), 401s on any
  missing field.
- `middleware.py` — `AuthMiddleware`. `PROTECTED_PREFIXES` declares
  which path families need a session; `BYPASS_PREFIXES`
  (`/api/github/setup`) and `BYPASS_METHODS` carve out anonymous
  exceptions. Attaches the `Session` to `request.state`.
- `workos.py` — process-wide lazy `AsyncWorkOSClient`. Login URL,
  code exchange, seal/load session.
- Tracing lives in `services/tracing/` (Langfuse handler + `@observe`
  + `flushTraces`). Unconfigured (empty keys) → helpers are no-ops,
  logs stay on the console.

## Notes

- Env vars are validated at startup; once `settings` loads, values
  are trusted downstream (no `*_configured` re-checks inside
  services).
