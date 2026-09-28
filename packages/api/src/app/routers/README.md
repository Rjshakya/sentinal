# routers — HTTP edge (validate + dispatch only)

One module per route family, all mounted under the `/api` prefix in
`main.py::create_app`. Routers never do durable work inline: they
validate, resolve the session/DB rows, and dispatch to a DBOS
workflow (202 + workflow id) or answer from the local mirror.
`__init__.py` is an empty marker; `main.py` imports each submodule
directly.

## Routes

- `health.py` — `GET /health` → `{"status": "ok"}`. Unguarded.
- `auth.py` — WorkOS OAuth: `GET /auth/login`, `GET
  /auth/callback` (sets the sealed session cookie, 302s to the
  dashboard), `POST /auth/logout`, `GET /auth/session`.
- `github.py` — App install flow + live repo reads:
  `GET /github/installation`, `GET /github/repos` (pass-through to
  `GET /installation/repositories`, deduped, flagged with
  `is_configured`), `DELETE /github/installation/{id}` (local
  forget), `GET /github/install-url` (signed install URL),
  `GET /github/setup` (GitHub redirect target; outside auth, verifies
  state, upserts the installation row, 302s to the dashboard).
- `ai.py` — `POST /ai/repo/setup`: bulk-insert one `Repo` row per
  requested repo (skips configured ones), synchronous.
- `users.py` — caller-scoped reads: `GET /users/repos`,
  `GET /users/stats` (prs reviewed, comments issued, P1 bugs
  caught — all joined through `pull_requests` so users never leak).
- `pulls.py` — live GitHub PR reads plus the local Sentinel mirror:
  `GET /pulls/{owner}/{repo}[/{number}[/commits|files|conversation|sentinel]]`.
- `reviews.py` — `GET /review` (list runs) and `POST /review`, the
  eval-only sync trigger gated by `X-Eval-Token`.
- `llm_configs.py` — per-user LLM config: `POST /` (probe then
  upsert), `POST /test` (probe only), `GET /` (stored rows, api key
  redacted). Always HTTP 200 with a `{data, success, error,
  test_result}` envelope, so the frontend never branches on status.
- `webhooks.py` — `POST /webhooks/github`: verifies
  `X-Hub-Signature-256` (401 on mismatch) and dispatches to the
  `github/webhook` sub-service (install events, PR opened, comments,
  pushes).
- `schemas/` — request/response Pydantic shapes, one module per
  router. See `schemas/README.md`.

## Notes

- Protected families are declared once in
  `core/middleware.py::PROTECTED_PREFIXES`; `/api/auth`,
  `/api/health`, and `/api/webhooks` stay outside it.
- `GET /github/setup` is the intentional anonymous exception inside
  a protected family (`BYPASS_PREFIXES`) — GitHub redirects the
  browser there with no session cookie.
