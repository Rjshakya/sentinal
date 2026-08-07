# Sentinel — Architecture

Sentinel is an AI-powered GitHub pull-request reviewer. It reads a developer's
diff, posts inline comments anchored to specific lines (tagged by severity), and
publishes a short prose review summary with an overall verdict at the top of the
PR, so reviewers can triage and merge with confidence.

This document is a present-tense architecture reference: it describes the system
as it exists in this repository. Run, test, and deploy commands are intentionally
omitted — see `README.md` for those.

## 1. Monorepo layout

```
ai-code-review/
├── pyproject.toml            # uv workspace root
├── docker-compose.yml        # Postgres 18
├── .env / .env.example       # backend env (loaded from repo root)
├── packages/
│   └── api/                  # FastAPI backend (uv member)
│       ├── pyproject.toml
│       ├── alembic.ini
│       ├── main.py           # uvicorn entry point (packages/api/main.py)
│       ├── alembic/
│       │   ├── env.py
│       │   └── versions/     # 12 revisions
│       └── src/app/
│           ├── core/         # config, db, auth, middleware, workos, github_app,
│           │                 #   install_state, sandbox/, llm, llm_callbacks, logging, result
│           ├── models/       # SQLModel tables + enums
│           ├── schemas/      # HTTP request/response shapes (setup, llm_config)
│           ├── repositories/ # generic Repository[T] base
│           ├── routers/      # health, auth, github, ai, users, llm_configs, webhooks
│           ├── services/     # agent/, review/, pr_issue_comment/, github/, llm_config/
│           └── utils/        # uuidToStr, etc.
└── web/                      # TanStack Start frontend (pnpm)
    ├── package.json
    ├── vite.config.ts
    ├── wrangler.jsonc
    ├── components.json       # shadcn/ui config (base-lyra, tabler)
    ├── tsr.config.json
    └── src/
        ├── router.tsx
        ├── routeTree.gen.ts  # generated; do not edit
        ├── routes/           # /, /login, /marketing, /dashboard(/repositories|settings)
        ├── components/       # layout + ui primitives
        ├── hooks/
        └── lib/              # api.ts, auth.ts, installation.ts, repos.ts, search.ts,
                              #   llm.ts, stats.ts, utils.ts, nav.tsx
```

Tooling posture: `uv` workspace for Python, `pnpm` for the web, `pyright`
configured at the root, `tsc` via Vite for the web, Alembic for schema
migrations. Python is pinned to 3.13. The API loads its environment from
`ai-code-review/.env` (the monorepo root), not from `packages/api/.env`.

## 2. System architecture

Three planes:

- **Web** — TanStack Start SPA, deployed to Cloudflare Workers. Owns the
  user-facing flows: sign-in, dashboard, GitHub App install, repo selection,
  setup kick-off, per-user LLM configuration.
- **API** — FastAPI monolith. Owns persistence, WorkOS User Management
  integration, the GitHub App client, the sandbox abstraction, and the DBOS
  durable review pipeline.
- **Integrations** — WorkOS for auth (User Management; sealed session cookies),
  a native **GitHub App** for repo access (installation tokens minted
  server-side via `githubkit`'s `AppAuthStrategy`), **E2B** (default) or
  **Daytona** for sandboxed code execution, and any LangChain-supported LLM
  provider (`openai:…`, `anthropic:…`, `google_genai:…`, …) for the review
  agents.

Postgres 18 is the only persistence tier, brought up by `docker-compose.yml`.
DBOS shares the same Postgres: `main.py::_dbos_config` strips the `+asyncpg`
driver suffix because DBOS creates its own (psycopg) engine.

Data flow at a glance:

1. Browser hits `/`, clicks "Sign in with GitHub/Google".
2. WorkOS runs OAuth and 302s to `/api/auth/callback?code=…`.
3. The API trades the code for tokens, seals a session into an httpOnly
   cookie (`wos_session`), and 302s the browser to `/dashboard`.
4. The dashboard calls `GET /api/github/installation`. If the user has no
   install, it offers an "Install on GitHub" button that calls
   `GET /api/github/install-url` (which signs an HMAC state token carrying
   the WorkOS `user_id`) and opens
   `https://github.com/apps/<slug>/installations/new?state=…` in a new tab.
5. GitHub redirects to `GET /api/github/setup`; the callback verifies the
   state, fetches the installation details, upserts a local `installations`
   row, and 302s back to `/dashboard?installation=success|failed`.
6. `/dashboard/repositories` calls `GET /api/github/repos` (a live
   pass-through to `GET /installation/repositories` across the user's
   installations) and lets the user pick repos to **Configure**, which
   POSTs to `/api/ai/repo/setup` (202, asynchronous DBOS dispatch).
7. GitHub webhook deliveries (verified by `X-Hub-Signature-256`) land on
   `POST /api/webhooks/github` and drive the durable review workflows:
   `pull_request` `opened` dispatches `review_workflow`;
   `issue_comment` `created` dispatches `trigger_issue_comment_workflow`,
   which classifies `@<app_slug> review` comments and dispatches the inner
   review workflow.

## 3. Backend — `packages/api`

### 3.1 Stack

- **FastAPI** on Python 3.13, async end-to-end
- **SQLModel** + **SQLAlchemy async** + **asyncpg** → PostgreSQL
- **DBOS** for durable workflows (its own psycopg engine on the same Postgres)
- **Alembic** for migrations
- **pydantic-settings** for env-driven configuration
- **WorkOS SDK** (`AsyncWorkOSClient`) for User Management
- **githubkit** (`AppAuthStrategy`) for the GitHub App REST surface
- **LangChain** (`init_chat_model`) + **deepagents** for the review agents
- **Sentry** for error capture (initialised only when `SENTRY_DSN` is set)

### 3.2 Module map

`main.py` (at `packages/api/main.py`, not `src/app/`) — the FastAPI
application. `create_app()` wires `CORSMiddleware` (`credentials=True`, so
sealed cookies round-trip), then `AuthMiddleware`, then registers the seven
routers under `settings.api_prefix` (`/api`). The `lifespan` hook runs
`create_db_and_tables()` (a `SQLModel.metadata.create_all` convenience for
greenfield dev), initialises DBOS from `_dbos_config()` and `DBOS.launch()`,
and calls `build_e2b_template()`; on shutdown it runs `DBOS.destroy()`.
Sentry is initialised at import time when `settings.sentry_configured`
(DSN present), with a `LoggingIntegration` that forwards ERROR+ records. On
Windows, the `__main__` block swaps uvicorn's asyncio loop factory to
`SelectorEventLoop` because psycopg async (used by DBOS) fails on the
`ProactorEventLoop`.

`src/app/core/`:

- `config.py` — `Settings(BaseSettings)` loaded from the monorepo-root
  `.env`. Groups: server (port, database_url, cors_origins, api_prefix),
  WorkOS (`workos_*`, `frontend_url`, `session_cookie_name`,
  `session_max_age_seconds`), sandbox (`sandbox_provider`, `e2b_*`,
  `daytona_*`), embeddings (`openai_api_key`), LLM (`llm_model` as a
  `"provider:model"` string, `llm_api_key`, `llm_base_url`,
  `llm_default_headers`, `llm_max_retries`, `llm_rate_limit_rps`,
  `llm_log_io`), GitHub App (`github_app_*`), DBOS (`dbos_executor_id`,
  `dbos_database_url`), GitHub webhook (`github_webhook_secret`), install
  flow (`github_install_state_secret`), Sentry (`sentry_*`). Convenience
  properties: `workos_configured`, `sandbox_configured`,
  `llm_configured` (accepts provider-native env vars via a provider→env-key
  map), `github_app_configured`, `github_webhook_configured`,
  `github_install_state_effective_secret`, `github_app_install_url`,
  `sentry_configured`, `cookie_secure`. All env vars have safe defaults so
  the module can import in tests.
- `db.py` — async engine + `async_session_maker`, `get_session` dependency,
  `create_db_and_tables`, and `dbos_datasource` (an
  `AsyncSQLAlchemyDatasource` created at import time via `asyncio.run` with a
  `SelectorEventLoop` factory; the `+asyncpg` suffix is stripped from the URL).
  `@dbos_datasource.transaction()` is what the durable `*_tx` steps use.
- `auth.py` — the `Session` pydantic model (user_id, user_name, email,
  profile_picture, session_id, external_id, created_at, updated_at,
  github_login) and `get_current_session` dependency: reads the cookie,
  `load_session` (local Fernet decrypt, no network IO), `session.authenticate()`,
  projects the user payload, extracts `github_login` from the
  `GitHubOAuth` connection's `connection_id`, and 401s on any missing field.
- `middleware.py` — `AuthMiddleware(BaseHTTPMiddleware)`. `PROTECTED_PREFIXES`
  = `/api/github`, `/api/ai`, `/api/users`, `/api/llm_config`.
  `BYPASS_PREFIXES` = `/api/github/setup` (GitHub calls it via a browser
  redirect with no session cookie). Skips `OPTIONS`; on success attaches the
  full `Session` plus flat fields (`user_id`, `session_id`, `email`,
  `user_name`, `profile_picture`) to `request.state`; on failure returns
  `{"detail": "Unauthorized"}` / 401.
- `workos.py` — single-process lazy `AsyncWorkOSClient`. Wraps
  `get_authorization_url(provider)` → `(url, state)`,
  `authenticate_code(code)`, `seal_session(auth_response)`, and
  `load_session(cookie_value)`. Session sealing/loading is local (Fernet),
  so no network IO on the hot path.
- `github_app.py` — GitHub App client factory. `get_app_github()` builds the
  process-wide `GitHub[AppAuthStrategy]` lazily from settings (private key
  from `GITHUB_APP_PRIVATE_KEY` base64 or the `*_PATH` file). Exposes
  `installation_client(installation_id)` (mints + caches installation
  tokens), `list_installation_repos` (paginated `GET /installation/repositories`),
  `mint_installation_token` (explicit token for the setup pipeline),
  `installation_id_for_repo(owner, repo)` (fallback resolution), and
  `get_installation` (for the setup callback).
- `install_state.py` — HMAC-signed state tokens for the install flow,
  stdlib-only: `base64url(payload) "." base64url(hmac_sha256(secret, payload))`
  with payload `"{user_id}|{exp_unix_seconds}"`, default TTL 600s.
  `sign(user_id, secret)` / `verify(token, secret)`.
- `sandbox/` — pluggable sandbox abstraction.
  - `base.py` — `BaseSandbox` ABC (create / connect / stop + spec access).
  - `types.py` — `SandboxSpec` (provider, api_key, template, cpu, memory…).
  - `factory.py` — `create_sandbox(spec=…)` picks the adapter; callers use
    `BaseSandbox`, never the concrete classes. `build_default_spec(provider)`
    builds a spec from settings, raising when the provider's key is missing.
  - `e2b.py` — `E2BSandbox` + `build_e2b_template()` (called at lifespan).
  - `daytona.py` — `DaytonaSandbox` adapter.
- `llm.py` — `LLMConfig` (frozen, DBOS-serializable: model as
  `"provider:model"`, api_key, base_url, headers, max_retries,
  rate_limit_rps; `provider` / `model_id` properties) and
  `build_chat_model(config, callbacks=…)` — the single factory delegating to
  `langchain.chat_models.init_chat_model`, applying rate limiter / base URL /
  default headers / SecretStr-wrapped api_key uniformly.
- `llm_callbacks.py` — `LLMIOCallbackHandler` + `make_llm_io_handler` for
  per-LLM-call JSON observability (metadata only; no prompt/output capture).
- `logging.py` — `JsonFormatter`, `configure_structured_logging()`,
  `structured_log(level, msg, object)`.
- `result.py` — `Ok` / `Err` result helpers used by the GitHub post path.

`src/app/models/` — see §3.4 Domain model. `__init__.py` re-exports every
table and enum so `from app.models import *` in `alembic/env.py` registers
them on `SQLModel.metadata`.

`src/app/routers/`:

- `health.py` — `GET /health` → `{"status": "ok"}`. Unguarded.
- `auth.py` — `GET /auth/login?provider=`, `GET /auth/callback?code=`,
  `POST /auth/logout`, `GET /auth/session`. Provider slugs map to WorkOS
  names (`google` → `GoogleOAuth`, `github` → `GitHubOAuth`). The callback
  302s to `FRONTEND_URL/dashboard` and sets the sealed cookie with
  `secure=True`, `httponly=True`, `samesite="lax"`.
- `github.py` — GitHub App routes:
  - `GET /github/installation` — the user's `InstallationStateOut`
    (`connected`, `installation_count`, per-installation details + repo count).
  - `GET /github/repos` — live pass-through: for each non-suspended
    installation, `list_installation_repos`; dedupes by GitHub repo id;
    cross-references the local `repos` table to flag `is_configured`.
    Fails with 502 when every installation errored.
  - `DELETE /github/installation/{installation_id}` — local "forget"
    (deletes `installations` rows; user must uninstall on github.com too).
  - `GET /github/install-url` — mints the signed install URL (503 when the
    App or the state secret is not configured).
  - `GET /github/setup` — GitHub's redirect target after install. Verifies
    the state token, fetches installation details, upserts the `installations`
    row (unique on `(user_id, github_installation_id)`), and 302s to
    `/dashboard?installation=success|failed&reason=…&setup_action=…`.
    Outside `AuthMiddleware`'s protected prefixes (in `BYPASS_PREFIXES`).
- `ai.py` — `POST /ai/repo/setup` (202): accepts `{repos: [{id, owner,
  name, installation_id}]}`, skips repos that already have a `repos` row,
  503s when the LLM is not configured, and dispatches one `setup_workflow`
  per repo with id `setup:{user_id}:{github_repo_id}`. `GET
  /ai/repo/setup/{workflow_id}` returns DBOS status plus the typed error
  name/message on terminal error; cross-user reads return 404 (the id
  encodes the owner).
- `users.py` — user-scoped reads: `GET /users/repos` (indexed `repos` rows)
  and `GET /users/stats` (`prs_reviewed`, `comments_issued`,
  `bugs_caught` = P1 comment count, all joined through `pull_requests` so
  another user's repos can never leak).
- `llm_configs.py` — per-user LLM config: `POST /` (test-and-upsert), `POST
  /test` (probe only), `GET /` (stored row, `api_key` redacted). All return
  the `{data, success, error, test_result}` envelope with HTTP 200 so the
  frontend never branches on status.
- `webhooks.py` — the GitHub App webhook receiver (see §3.5).

`src/app/services/`:

- `agent/` — the review-agent schemas + prompts + setup pipeline.
  - `models.py` — `CodeCommentDraft`, `ReviewComments` (mixed severities),
    `SummaryResult`, `ReviewResult`.
  - `prompts.py` — `PR_SUMMARY_SYSTEM_PROMPT` (summarizer agent) and
    `REVIEW_COMMENTS_SYSTEM_PROMPT` (the merged security/correctness/style
    rubric assigning P1_CRITICAL / P2_WARNING / P3_NITPICK).
  - `helpers.py` — small prompt/result helpers (`extract_message_kinds`).
  - `setup_workflow/` — the durable per-repo setup workflow:
    `ensure_repo_and_sandbox_step` → `mint_installation_token_step` →
    `git_clone_step` → (`finally`) `stop_setup_sandbox_step`. Typed errors in
    `errors.py`, Pydantic surface in `types.py` (`SetupWorkflowInput`,
    `RepoContext`, `SetupWorkflowResult`), pure helpers in `_helpers.py`.
    Workflow id `setup:{user_id}:{github_repo_id}`.
- `review/` — the durable review pipeline.
  - `workflow.py` — the top-level `review_workflow` DBOS orchestrator (see
    §3.5).
  - `webhook.py` — the `pull_request` adapter: `handle_pull_request_opened`
    classifies the action (`opened` only — `synchronize` is no longer a
    trigger), resolves user/repo, gates on LLM + sandbox config, resolves
    the per-user LLM config, and dispatches `review_workflow` with the
    deterministic id `review:{repo_id}:{pr_number}:{head_sha[:7]}`.
  - `workflow_types.py` — the Pydantic models crossing the workflow
    boundary: `ReviewWorkflowInput`, `PostReviewInput`, `ReviewRunResult`,
    `PostReviewResult`, `RepoSnapshot`, `ResolvedSandbox`, plus the
    `TotalUsages` / `TotalUsagesPerPR` token envelopes.
  - `_internal.py` — `_e2b_spec()` and the `_SHOULD_RETRY_TRANSIENT` /
    `_SHOULD_RETRY_AGENT` predicates passed to durable steps.
  - `diff.py` — unified-diff parsing; `parse_and_write_diff_json` writes
    `diff.json` (the JSON hunk map) alongside the diff in the sandbox.
  - `hunk_map.py` — the `HunkMap` type (`files[file_name][RIGHT|LEFT]` line
    sets) and the pure `filter_drafts(review, hunk_map)` backstop.
  - `tools.py` — `make_get_diff_tool` (the shared sandbox `get_diff` tool).
  - `agent.py` — agent factories for the **two parallel agents**
    (`build_summary_agent` + `build_comments_agent`, both taking a
    `middleware=build_review_middleware()` stack; plus
    `create_review_llm_models`, `build_review_agents`, and the pure
    `combine_review_results` (severity-sorted P1→P2→P3) +
    `verdict_for(comments)` rule (any P1 → REQUEST_CHANGES; else any
    P2/P3 → COMMENT; else APPROVE). Structured output is `response_format`
    (schema bound as a forced tool); for OpenAI-compatible endpoints
    that reject forced tool choice (DeepSeek → HTTP 400 on
    `tool_choice="required"`), `_uses_text_json_output` drops the schema
    and appends a strict JSON output contract to the prompt instead.
  - `middleware.py` — `build_review_middleware()`: the shared built-in
    agent middleware stack (`ModelRetryMiddleware` max 3 retries, 2x
    backoff, `on_failure="error"`; `ModelCallLimitMiddleware` run cap 50;
    `ToolCallLimitMiddleware` run cap 200) wired into both review agents.
  - `errors.py` — typed error variants for the pipeline.
  - `steps/` — one file per I/O boundary, each exposing a pure helper and a
    DBOS-wrapped variant: `resolve_repo`/`resolve_repo_tx`,
    `resolve_sandbox`/`resolve_sandbox_step`, `fetch_diff_step`,
    `parse_diff_step`, `upsert_pr`/`upsert_pull_request_tx`,
    `invoke_agent` (the two parallel agent steps + `combine_agent_outcomes`),
    `persist_summary`/
    `persist_review_summary_tx`, `persist_comments`/
    `persist_code_comments_tx`, `persist_usage`/`persist_review_usage_tx`,
    `stop_sandbox_step`.
- `pr_issue_comment/` — the comment-trigger path.
  - `workflow.py` — `trigger_issue_comment_workflow` (id
    `trigger_issue_comment:{comment_id}`): validate → classify
    (`action` / `is_pr` / `is_self` / `has_mention` / `is_authorized`) →
    resolve installation → resolve repo → env gate → fetch PR state →
    best-effort 👀 reaction → resolve per-user LLM config → build inner
    `ReviewWorkflowInput` → dispatch `review_workflow` with the
    deterministic id. Every skip path returns `TriggerRunResult` with a
    `skip_reason` instead of raising.
  - `helpers.py` — pure `validate_comment_payload` / `classify_comment`.
  - `types.py` — `TriggerRunResult`, `IssueCommentTriggerInput`.
  - `steps/` — `resolve_installation`, `resolve_repo_id`, `fetch_pr_state`,
    `add_reaction`, `resolve_llm_config`, `build_review_input`,
    `dispatch_review`.
- `github/` — the GitHub post-pipeline.
  - `post_review.py` — pure conversions (`convert_to_github_*`),
    `post_review_to_github` (the REST call via an installation client),
    `GitHubPosterError` variants, and the DB-update helpers.
  - `workflow.py` — `post_review_to_github_workflow` (id
    `post:{repo_id}:{pr_number}:{head_sha[:7]}`) wrapping the single
    `post_review_to_github_step` (`retries_allowed=True`, `max_attempts=3`,
    retry only on `RetryableGitHubPostError` — 5xx / 429). Non-retryable
    errors complete the workflow with `posted=False`.
  - `steps/` — placeholder for future sub-step helpers.
- `llm_config/` — plain async service (no DBOS workflow):
  `test_user_llm_config` (never raises; runs a `create_deep_agent`
  probe with a `response_format` pydantic schema — the same
  structured-output path the review agents use — and validates the
  `structured_response`), `upsert_user_llm_config` (probe
  then upsert), `list_user_llm_configs`,
  `resolve_active_llm_config(user_id)` (used by the review webhook; raises
  `NoActiveLLMConfigError` when the user has no row).

### 3.3 Config surface at a glance

The `Settings` object is the single source of truth for the environment.
Routes 503 when their dependency is not configured (`workos_configured`,
`llm_configured`, `sandbox_configured`, `github_app_configured`,
`github_webhook_configured`). The webhook receiver 401s all deliveries when
`GITHUB_WEBHOOK_SECRET` is unset. `LLM_MODEL` is a single `provider:model`
string consumed by LangChain's `init_chat_model`; `LLM_API_KEY` falls back
to the provider's native env var (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`,
`GOOGLE_API_KEY`, …) — see the `_PROVIDER_ENV_KEY` map in `config.py`.

### 3.4 Domain model

Eight tables; UUID (string, `uuidToStr()`) primary keys, timestamps are
`TIMESTAMP(timezone=True)` with `now()` server defaults, CASCADE deletes at
the DB layer with `passive_deletes=True` on relationships.

```
repos
├── id                str  PK
├── user_id           str  index
├── org_id            str?
├── github_repo_id    bigint  UNIQUE
├── repo_name         str
├── repo_owner        str
├── clone_url         str(1024)
├── url               str?          (html_url)
├── private           bool
├── default_branch    str?
└── created_at / updated_at

installations
├── id                str  PK
├── user_id           str  index
├── github_installation_id  bigint  UNIQUE
├── account_login     str(255)
├── account_type      str(16)
├── repository_selection  str(16)
├── suspended_at      timestamptz?
└── created_at / updated_at

sandboxes
├── id                str  PK
├── user_id           str
├── repo_id           str  → repos.id  CASCADE
├── sandbox_name      str
├── state             STARTED|PAUSED|STOPPED|DELETED|ARCHIVED
├── provider_id       str?          ('e2b' | 'daytona')
├── started_at / stopped_at  timestamptz?
└── created_at / updated_at

llm_configs
├── id                str  PK
├── user_id           str  index
├── provider          str
├── model_id          str
├── base_url          str
├── api_key           str           (plain str; redacted by the router)
└── created_at / updated_at

pull_requests
├── repo_id           str  → repos.id  CASCADE
├── github_pr_id      bigint  UNIQUE
├── number            int  UNIQUE(repo_id, number)
├── author            str(255)
├── title             str(1024)
├── body              text?
├── status            OPEN|CLOSED|MERGED
├── base_branch / base_sha
├── head_branch / head_sha
└── created_at / updated_at

code_comments
├── pr_id             str  → pull_requests.id  CASCADE
├── commit_id         str            (head sha; no FK — commit_snapshots was dropped)
├── github_comment_id bigint?        (back-link to the comment posted on GitHub)
├── file_name         str(1024)
├── comment           text
├── severity          P1_CRITICAL | P2_WARNING | P3_NITPICK
├── from_line / to_line
├── side              RIGHT | LEFT
├── node_type         str(128)?
├── state             ACTIVE | OUTDATED | RESOLVED
└── created_at / updated_at
   INDEX (commit_id, file_name, state)

review_summaries
├── pr_id             str  → pull_requests.id  CASCADE
├── commit_id         str            UNIQUE (head sha; no FK)
├── github_review_id  bigint?        (back-link to the GitHub PR review)
├── summary           text
├── verdict           APPROVE | COMMENT | REQUEST_CHANGES
└── created_at

review_usages
├── id                str  PK
├── user_id           str  index
├── pr_id             str  → pull_requests.id  CASCADE
├── pr_number         int
├── repo_id           str  → repos.id  CASCADE
├── review_summary_id uuid? → review_summaries.id  CASCADE
├── review_status     SUCCESS | FAILED
├── input_tokens / output_tokens / total_tokens  int
├── input_token_details  jsonb?     (cache_read / cache_creation)
└── created_at / updated_at
```

Enums (Python and DB-checked): `PRStatus`, `CommentSeverity`,
`CommentSide`, `CommentState`, `ReviewVerdict`, `SandboxState`,
`ReviewRunStatus`. The relationship graph: `Repo` 1—N `PullRequest`,
`PullRequest` 1—N `CodeComment` and 1—1 `ReviewSummary` (per commit),
1—N `ReviewUsage`.

### 3.5 Request lifecycles

**Authentication.** `/auth/login?provider=github|google` returns a 302 to
WorkOS's authorize URL. WorkOS runs the OAuth dance and 302s to
`/auth/callback?code=…`. The callback calls `authenticate_code`, seals the
response, sets the `wos_session` cookie (`secure=True`, `httponly=True`,
`samesite=lax`), and 302s to `FRONTEND_URL/dashboard`.

**Protected routes.** `AuthMiddleware` runs on every non-OPTIONS request
whose path starts with `/api/github`, `/api/ai`, `/api/users`, or
`/api/llm_config` (with `/api/github/setup` bypassed). It loads the sealed
cookie, authenticates locally (Fernet decrypt + JWT verify, no network IO),
and on success populates `request.state`. Failures return
`{"detail": "Unauthorized"}` / 401. `/api/auth`, `/api/health`, and
`/api/webhooks` are outside the guard list.

**GitHub App install.** The dashboard calls `GET /api/github/install-url`
(protected); the API signs an HMAC state token carrying the WorkOS
`user_id` and returns `https://github.com/apps/<slug>/installations/new?state=…`.
After the user grants, GitHub redirects to `/api/github/setup?installation_id=…&state=…&setup_action=…`.
The callback verifies the token, fetches installation details via the App
client, upserts the `installations` row, and 302s to
`/dashboard?installation=success|failed`. Subsequent `installation_repositories
added` webhooks upsert `repos` rows for the same owner.

**List repos.** `GET /github/repos` mints an installation-scoped GitHub
client per installation and merges `GET /installation/repositories`
responses, deduped by GitHub repo id, with `is_configured` from the local
`repos` table.

**Webhook receiver.** `POST /api/webhooks/github` verifies
`X-Hub-Signature-256` against `GITHUB_WEBHOOK_SECRET` (401 on mismatch or
when unconfigured) and routes by `X-GitHub-Event`:
`ping` → 200; `installation.created` → no-op (setup callback is the source
of truth); `installation.deleted` → delete rows; `suspend`/`unsuspend` →
toggle `suspended_at`; `installation_repositories.added` → upsert one
`repos` row per added repo (user recovered from the `installations` row);
`removed` → delete rows; `pull_request.opened` → `handle_pull_request_opened`
(dispatches `review_workflow`); `issue_comment.created` →
`handle_issue_comment_created` (dispatches `trigger_issue_comment_workflow`);
everything else → 202 with a log line.

**Setup pipeline.** `POST /ai/repo/setup` (202) dispatches one
`setup_workflow` per new repo: `ensure_repo_and_sandbox_step` (writes the
`repos` + `sandboxes` rows) → `mint_installation_token_step` (GitHub
installation token, passed into the sandbox as `GITHUB_TOKEN` for the
clone) → `git_clone_step` → `stop_setup_sandbox_step` in `finally`. The
router's GET endpoint polls DBOS status.

**Review pipeline.** Two triggers dispatch `review_workflow`:

1. GitHub `pull_request` `opened` webhook →
   `review.webhook.handle_pull_request_opened` (validates, resolves owner +
   repo, gates config, resolves the per-user LLM config).
2. A PR comment mentioning `@<app_slug> review` →
   `pr_issue_comment.workflow.trigger_issue_comment_workflow` (id
   `trigger_issue_comment:{comment_id}`; classify → resolve → 👀 → dispatch).

Both start the workflow with the deterministic id
`review:{repo_id}:{pr_number}:{head_sha[:7]}`, so duplicate deliveries for
the same head SHA do not re-run the agent. `review_workflow` then runs:

1. `resolve_repo_tx` — look up the `Repos` row (`@dbos_datasource.transaction`).
2. `resolve_sandbox_step` — look up the active `Sandbox` row and connect to
   the E2B sandbox (`@DBOS.step`). Only the sandbox **id** travels onward;
   each step reconnects.
3. `fetch_diff_step` — `git diff base_sha...head_sha` written to the
   sandbox (`file.diff`).
4. `parse_diff_step` — parse the diff into a `HunkMap` and write
   `diff.json` alongside it. The `HunkMap` is the source of truth for which
   `(file, line, side)` anchors GitHub will accept.
5. `upsert_pull_request_tx` — insert/update the `PullRequest` row.
6. `invoke_summary_agent_step` / `invoke_comments_agent_step` — the
   **two parallel agent steps**, started concurrently from the workflow
   body via `asyncio.gather(return_exceptions=True)` (the documented DBOS
   parallel-steps pattern; deterministic start order). Each
   (`@DBOS.step`, `retries_allowed=True`, `max_attempts=3`,
   `backoff_rate=2`, retry predicate `_SHOULD_RETRY_AGENT`) reconnects to
   the shared E2B sandbox by id, builds its own chat model + deep-agent
   (`summarizer` / `comments`, each with the `get_diff` tool and the
   `build_review_middleware()` stack), runs it, wraps failures in the
   per-lane error class
   with a `retryable` flag, and returns `(result, usage)`. A transient
   failure retries **that lane alone**; the invoke steps never stop the
   sandbox (the workflow's `finally` owns the stop). `combine_agent_outcomes`
   then partitions the two results: both failed → raises
   `ReviewAgentsInvocationError` (pushed to Sentry with run context);
   partial → failed lanes degrade to empty defaults (`""` summary / empty
   comment lists) with a warning log, and the review completes with the
   successful lanes' output; token usage is aggregated per model from
   successful lanes only.
7. `filter_drafts(review, hunk_map)` — pure server-side backstop that drops
   any draft whose anchor is not in the `HunkMap`.
8. `persist_review_summary_tx` + `persist_code_comments_tx` — one
   `ReviewSummary` row and one `CodeComment` row per surviving draft.
9. `persist_review_usage_tx` — one `ReviewUsage` row with aggregated token
   counts (success path; `review_status=SUCCESS`).
10. `stop_sandbox_step` — always, in a `finally`.

The summary in `review_summaries.summary` is the `summarizer` agent's
markdown output (from its `SummaryResult` structured response), and the verdict is
recomputed deterministically in code by `verdict_for()` from the merged
severities (any P1 → `REQUEST_CHANGES`, else any P2/P3 → `COMMENT`, else
`APPROVE`).

If `post_to_github` is enabled (always true on the webhook path), the
workflow starts `post_review_to_github_workflow` with id
`post:{repo_id}:{pr_number}:{head_sha[:7]}`. This durable workflow retries
transient GitHub errors (5xx / 429) up to 3 attempts and can be restarted
independently via the DBOS admin server without re-running the LLM. The
main workflow completes regardless of the post outcome.

**Diff parsing and comment-line validation.** GitHub's review-comments API
rejects (422) any inline comment whose `(file, line, side)` anchor is not in
the PR's diff. Three layers guard this:

1. **Agent self-validation (prompt-driven).** The comments agent
   reads `/home/user/tmp/{pr_number}/{head_sha}/diff.json` (the JSON
   hunk map written by `parse_diff_step`) and confirms every draft's
   `from_line` is in `files[file_name][side]`; if not, it re-anchors to the
   nearest in-bounds line in the **same hunk**, or drops the comment.
2. **Server-side backstop.** `filter_drafts(review, hunk_map)` — one pure
   call in the workflow body, immediately after the agent step, before any
   persist/post step.
3. **`< 1` guard.** `convert_to_github_comments` still rejects drafts with
   `from_line < 1` (or `to_line < 1`) as final defence-in-depth.

### 3.6 Migrations

`packages/api/alembic/versions/` holds 12 revisions. The oldest is
`0001_init` (the five original tables), then `0002_extend_repos_and_sandboxes`,
`243a7473b750_add_indexing_status`, `d2c05e88f8e9_drop_commit_snapshots_and_fix_fks`,
`951a82befdb3_sandbox_provider_id_add`, `d11be80b25c9_` (installations),
`51b6db2b00c0_`, `5d1d3894e8a5_`, `fd84562ca886_drop_repo_setup_result_table`,
`6f386ff6d9a4_add_llm_config_and_review_usages`, `fb1f0819aade_`, and
`efc8cecac0b4_`. Schema changes go through Alembic; the lifespan's
`create_all` is a convenience for greenfield dev, not a substitute.

### 3.7 Structured logging + Sentry

The API emits all logs as JSON (`configure_structured_logging()` replaces
the root formatter with `JsonFormatter`). Failures in the review path are
logged via `structured_log` and pushed to Sentry when `SENTRY_DSN` is set:
`combine_agent_outcomes` captures `ReviewAgentsInvocationError` with the
full run context (PR, SHAs, user, LLM provider/model, failed/succeeded
agents, workflow id) as tags and extras. When `LLM_LOG_IO` is enabled, every
LLM call from the review agents emits `llm_call_started` /
`llm_call_completed` / `tool_call_*` lines with correlation context; the
handler never captures prompt or output text.

## 4. Frontend — `web`

### 4.1 Stack

- **TanStack Start** — SSR-capable React framework with file-based routing;
  the route tree is auto-generated into `src/routeTree.gen.ts`.
- **React 19** + **Vite**, **Tailwind CSS 4** via `@tailwindcss/vite` with a
  custom `dark` variant.
- **shadcn/ui** in the `base-lyra` style with `tabler` icons
  (`components.json`).
- **TanStack Query** for server state, **TanStack Router Devtools** in dev.
- **Cloudflare Workers** as the deploy target (`wrangler.jsonc`,
  `nodejs_compat`).
- **Geist / Geist Mono** variable fonts.

### 4.2 Module map

- `src/routes/__root.tsx` — HTML shell: blocking theme-init script in
  `<head>`, a single `QueryClient`, `QueryClientProvider` + `TooltipProvider`,
  global `Toaster`, devtools panel.
- `src/lib/`:
  - `api.ts` — typed `fetch` wrapper. `apiBaseUrl` from `VITE_API_URL`;
    `credentials: "include"` on every call. `ApiError` carries status +
    body. Exposes `session`, `logout`, `installation`, `forgetInstallation`,
    `repos`, `userRepos`, `userStats`, `setup`, `codeSearch` (client stub —
    no backend route yet), `installUrl`, `getLlmConfig`, `updateLlmConfig`,
    `testLlmConfig`.
  - `auth.ts` — `useSession` (query against `/auth/session`),
    `protectPage` (`beforeLoad` guard — redirects to `/` on failure),
    `useLogout`.
  - `installation.ts` — `useInstallation`, `useInstallUrl`, and the
    `useForgetInstallation` mutation (invalidates installation + repo keys).
  - `repos.ts` — `useRepos` and `useSetup`.
  - `search.ts` — code-search UI state (route not implemented server-side).
  - `llm.ts` — `useLlmConfig`, `useUpdateLlmConfig`, `useTestLlmConfig`.
  - `stats.ts` — `useUserStats`.
  - `utils.ts` — `cn` (clsx + twMerge).
  - `nav.tsx` — dashboard nav (Overview, Repositories, Reviews, Settings)
    with tabler icons.

### 4.3 Route tree

```
/                    index.tsx          (landing page via marketing/_components)
/login               login.tsx
/dashboard           route.tsx          (SidebarProvider + Outlet)
  /                  index.tsx          (overview: greeting, stat cards,
                                        GitHub connection card, actions card)
  /repositories      route.tsx          (repo list + code search)
  /settings          route.tsx          (per-user LLM config card)
/marketing/_components/…                (landing page sections)
```

`/dashboard/reviews` appears in the sidebar nav (`lib/nav.tsx`) but the
corresponding route file does not exist yet.

### 4.4 Data flow

- `GithubConnectionCard` (dashboard overview + repositories) reads
  `/github/installation`; if disconnected it renders "Install on GitHub",
  which calls `/github/install-url` and opens the URL in a new tab. After
  the setup-callback redirect (`?installation=success|failed`) the tab
  toasts the outcome.
- `RepositoriesPage` lists repos via `useRepos` (`/github/repos`), lets the
  user check off unconfigured repos, and "Configure" POSTs to
  `/ai/repo/setup`, toasting the accepted count.
- `SettingsPage` renders the `LlmConfigCard`: `useLlmConfig` loads the
  stored row, `useTestLlmConfig` probes without persisting,
  `useUpdateLlmConfig` probes then upserts. Provider is a `Select` of the
  common LangChain prefixes with a free-form fallback.
- `useLogout` clears the session query, invalidates it, and invalidates the
  router so `protectPage` re-runs and redirects.

## 5. Cross-cutting conventions

- **Async end-to-end on the backend.** No sync DB calls, no sync WorkOS
  client. Session loading is local-only (Fernet-sealed cookie).
- **Auth is opt-in per route group.** `AuthMiddleware.PROTECTED_PREFIXES`
  is the single declaration of which path families require a session; new
  protected groups are added there, and anonymous exceptions to a protected
  family go in `BYPASS_PREFIXES`.
- **Webhooks are the only anonymous I/O surface** and are HMAC-verified;
  the webhook router never trusts the caller's identity.
- **TanStack Query owns server state on the web.** No `useEffect` fetching;
  `ApiError` is the failure contract.
- **Durable work belongs in DBOS workflows.** Routers only validate +
  dispatch; workflows checkpoint every I/O step, and transient errors are
  retried per-step via `should_retry` predicates.
- **Workflow ids are deterministic and encode the domain**
  (`setup:{user_id}:{gh_repo_id}`, `review:{repo_id}:{pr}:{head_sha[:7]}`,
  `post:{…}`, `trigger_issue_comment:{comment_id}`) so duplicate deliveries
  dedupe and restarts are safe.
- **LLM configuration is a frozen value object** (`LLMConfig`) resolved
  per-user at review time (`resolve_active_llm_config`, falling back to
  `settings.llm_config`), consumed only through `build_chat_model`.
- **Sandbox access goes through `BaseSandbox`**; the factory is the only
  place that imports E2B/Daytona adapters.
- **SQLModel is the source of truth for the schema**, Alembic mirrors it,
  CASCADE deletes live at the DB layer with `passive_deletes=True`.
- **Severity and verdict are enums, not free text.**
- **Cookies are sealed, not signed.** `secure=True` is hard-coded in
  `auth.py`; non-HTTPS callbacks will not work in production.
- **shadcn/ui style is `base-lyra`, icons are `tabler`.**
- **API base URL is `VITE_API_URL`** (prefix included); all calls send
  `credentials: "include"`.

## 6. Configuration surface

### 6.1 Backend (`packages/api`, loaded from monorepo-root `.env`)

| Variable | Default | Purpose |
| --- | --- | --- |
| `DATABASE_URL` | `postgresql+asyncpg://postgres:postgres@localhost:5432/aicode` | Async SQLAlchemy URL |
| `CORS_ORIGINS` | `["http://localhost:3000"]` | Allowed origins (JSON array in env) |
| `API_PREFIX` | `/api` | Prefix for every router registration |
| `WORKOS_API_KEY` / `WORKOS_CLIENT_ID` | `""` | WorkOS User Management credentials |
| `WORKOS_REDIRECT_URI` | `http://localhost:8000/api/auth/callback` | Must match the WorkOS dashboard |
| `WORKOS_COOKIE_PASSWORD` | `""` | ≥32 random chars; seals the session cookie |
| `FRONTEND_URL` | `http://localhost:3000` | Post-login redirect target |
| `SANDBOX_PROVIDER` | `e2b` | `e2b` or `daytona` |
| `E2B_API_KEY`, `E2B_TEMPLATE`, `E2B_CPU_COUNT`, `E2B_MEMORY_MB`, `E2B_TIMEOUT_S` | `""` / `code-interpreter-v1` / `2` / `2048` / `1200` | E2B sandbox defaults |
| `DAYTONA_API_KEY`, `DAYTONA_TEMPLATE` | `""` | Daytona adapter config |
| `LLM_MODEL` | `""` | `provider:model` string for the review agents |
| `LLM_API_KEY` / `LLM_BASE_URL` / `LLM_DEFAULT_HEADERS` | `""` / `""` / `{}` | Provider credential / gateway base URL / headers |
| `LLM_MAX_RETRIES` / `LLM_RATE_LIMIT_RPS` / `LLM_LOG_IO` | `3` / `0.5` / `false` | SDK retries, client-side rate limit, per-call I/O logging |
| `GITHUB_APP_ID` / `GITHUB_APP_CLIENT_ID` / `GITHUB_APP_CLIENT_SECRET` / `GITHUB_APP_SLUG` | `""` | GitHub App identity |
| `GITHUB_APP_PRIVATE_KEY` / `GITHUB_APP_PRIVATE_KEY_PATH` | `""` | App private key (base64 or PEM path) |
| `GITHUB_WEBHOOK_SECRET` | `""` | HMAC secret for `X-Hub-Signature-256` |
| `GITHUB_INSTALL_STATE_SECRET` | `""` | HMAC secret for install-flow state; falls back to `WORKOS_COOKIE_PASSWORD` |
| `DBOS_EXECUTOR_ID` / `DBOS_DATABASE_URL` | hostname / `postgresql://…@localhost:5432/aicode` | DBOS executor identity / DB URL |
| `SENTRY_DSN` / `SENTRY_ENVIRONMENT` / `SENTRY_TRACES_SAMPLE_RATE` / `SENTRY_PROFILES_SAMPLE_RATE` | `""` / `development` / `1.0` / `1.0` | Sentry observability |

### 6.2 Frontend (`web/.env`)

| Variable | Default | Purpose |
| --- | --- | --- |
| `VITE_API_URL` | — | Base URL for the API, including the API prefix (e.g. `http://localhost:8000/api`) |
| `VITE_GITHUB_APP_SLUG` | `ai-code-review` | Display name for the GitHub App (used in copy) |

## 7. Deployment shape

- **Web** targets Cloudflare Workers (`wrangler.jsonc`,
  `compatibility_flags: ["nodejs_compat"]`,
  `@tanstack/react-start/server-entry`).
- **API** is a plain FastAPI app — BYO host. Expects Postgres 18 at
  `DATABASE_URL` (DBOS shares it; the `+asyncpg` suffix is stripped) and
  the env vars above. Migrations are forward-only.

## 8. Where to find things

- FastAPI entry point → `packages/api/main.py`
- Settings / env surface → `packages/api/src/app/core/config.py`
- Database schema → `packages/api/alembic/versions/`
- ORM models → `packages/api/src/app/models/`
- API routers → `packages/api/src/app/routers/`
- GitHub App client + install state → `packages/api/src/app/core/{github_app,install_state}.py`
- Sandbox abstraction → `packages/api/src/app/core/sandbox/`
- LLM factory (`LLMConfig` + `build_chat_model`) → `packages/api/src/app/core/llm.py`
- AI agent prompts → `packages/api/src/app/services/agent/prompts.py`
- AI agent response schemas → `packages/api/src/app/services/agent/models.py`
- Review pipeline (workflow + steps + agent fan-out) → `packages/api/src/app/services/review/`
- Comment-trigger workflow → `packages/api/src/app/services/pr_issue_comment/`
- GitHub post workflow → `packages/api/src/app/services/github/`
- Setup workflow → `packages/api/src/app/services/agent/setup_workflow/`
- Per-user LLM config service + routes → `packages/api/src/app/services/llm_config/`, `packages/api/src/app/routers/llm_configs.py`
- Webhook receiver → `packages/api/src/app/routers/webhooks.py`
- Route tree → `web/src/routeTree.gen.ts` (generated)
- Pages → `web/src/routes/`
- API client + auth hooks → `web/src/lib/{api,auth,installation,repos,llm,stats}.ts`
- Env files → `ai-code-review/.env` (API), `web/.env` (Vite)
