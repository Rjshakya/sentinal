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
│           ├── services/     # agent/, setup/, indexing/, github/, llm_config/
│           ├── workflows/    # review/ (durable review pipeline + triggers)
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
   `pull_request` `opened` and `issue_comment` `created` (mentioning
   `@<app_slug> review`) both dispatch `reviewWorkflow` via
   `workflows/review/triggers.py`.

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
- `result.py` — `Ok` / `Err` result helpers (currently unused; retained
  for future result-style services).

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
- `indexing.py` — indexing-pipeline routes:
  - `POST /indexing/repo` (202): accepts `{repo_owner, repo_name, repo_url,
    default_branch?}`. The client supplies `repo_owner` + `repo_name`
    as canonical identifiers (it already has them on the `Repo` row),
    so the handler trusts them and skips URL parsing. Verifies the
    repo is in the user's `repos` table (`404` otherwise) and dispatches
    `indexRepo` under the deterministic id `index:{owner}:{repo}`.
  - `GET /indexing/{workflow_id}` — return the `IndexRun` row for the
    workflow id; `404` on cross-user reads.
  - `GET /indexing` — list the user's runs, paginated newest-first.
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

- `agent/` — the review-agent schemas + prompts.
  - `models.py` — `CodeCommentDraft`, `ReviewComments` (mixed severities),
    `SummaryResult`, `ReviewResult`.
  - `prompts.py` — `PR_SUMMARY_SYSTEM_PROMPT` (summarizer agent) and
    `REVIEW_COMMENTS_SYSTEM_PROMPT` (the merged security/correctness/style
    rubric assigning P1_CRITICAL / P2_WARNING / P3_NITPICK).
  - `helpers.py` — small prompt/result helpers (`extract_message_kinds`).
- `setup/` — the durable per-repo setup workflow:
  `ensure_repo_and_sandbox_step` → `mint_installation_token_step` →
  `git_clone_step` → (`finally`) `stop_setup_sandbox_step`. Typed errors in
  `errors.py`, Pydantic surface in `types.py` (`SetupWorkflowInput`,
  `RepoContext`, `SetupWorkflowResult`), pure helpers in `_helpers.py`.
  Workflow id `setup:{user_id}:{github_repo_id}`. When
  `index_after_setup` is true (router sets it from
  `Settings.indexing_configured`), the workflow fires off `indexRepo`
  fire-and-forget as its final step.
- `indexing/` — the full-indexing pipeline: tree-sitter chunking in
  the sandbox, LanceDB ingest + S3 persistence inside the same
  sandbox.
  - `workflow.py` — `indexRepo` (id `index:{owner}:{repo}`): index
    run row → sandbox create → authenticated clone URL → shallow
    clone → upload scripts → combined chunking + ingestion
    (`mode="overwrite"` full rewrite) → success/error mirrors; sandbox
    killed in `finally`. Lifecycle mirror rows live in `index_runs`.
  - `helpers.py` — pure helpers (`build_table_uri`, `index_workflow_id`,
    `parse_index_summary`); `types.py` — frozen workflow input/context;
    `errors.py` — the `IndexingError` hierarchy + `_should_retry_index`.
  - `steps/` — `ensureIndexSandbox`, `getRepoUrl` (installation token
    → authenticated clone URL), `gitCloneToSandbox`,
    `uploadScriptsToSandbox`, `runIndexPipeline` (`run_index.py`),
    `index_run_steps.py` (best-effort `index_runs` mirror),
    `update_repo.py` (best-effort `repos.is_indexed` mirror),
    `stop_sandbox.py` (finally).
  - `scripts/` — in-sandbox files uploaded as bytes (never imported
    on the host): `chunking.py` (tree-sitter generator), `ingestion.py`
    (LanceDB writer).
  - `incremental/` — the incremental-indexing pipeline, triggered by
    GitHub `push` webhooks on the default branch.
    - `webhook.py` — `handle_push_event` (the push adapter): default
      branch check → aggregate changed files across all commits →
      resolve user/repo → gate on `is_indexed` + indexing config →
      dispatch `incrementalIndexRepo`. Every skip path returns a
      `PushWebhookAck` with a `skip_reason`.
    - `workflow.py` — `incrementalIndexRepo` (id
      `index:{owner}:{repo}:{head_sha[:7]}`): host-side delete of the
      `removed + modified` chunks → (only when files remain) a fresh
      index sandbox → clone → upload scripts → append-only in-sandbox
      ingest. Success mirrors keep `is_indexed = true`; **errors never
      flip `is_indexed`** (the dataset still exists).
    - `steps/` — `delete_stale_chunks.py` (host-side
      `lancedb.connect_async` + `table.delete`, no sandbox),
      `ensure_sandbox.py` (fresh E2B sandbox per run),
      `upload_scripts.py` (uploads shared `chunking.py` +
      incremental `incremental_ingestion.py`),
      `run_incremental_ingest.py` (the append command).
    - `scripts/incremental_ingestion.py` — in-sandbox append-only
      LanceDB writer for the explicit file list + FTS rebuild.
    - `helpers.py` — pure `push_skip_reason`, `extract_push_files`,
      `incremental_workflow_id`, `build_delete_predicates`.
- `workflows/review/` — the refactored durable review pipeline (the
  successor of the legacy `services/review/` + `services/pr_issue_comment/`
  packages, which were removed), built on the §9 service layer.
  - `workflow.py` — the `reviewWorkflow` DBOS orchestrator (see §3.5)
    plus the pure helpers `createReviewWorkflowId` (the deterministic
    `review:{repo_id}:{pr_number}:{head_sha[:7]}` id),
    `computeReviewLimits` (sizes the per-run agent call limits from the
    PR's size stats), and `buildReviewWorkflowInput`.
  - `triggers.py` — the webhook edge adapters (the successor of the
    legacy `review.webhook` + `pr_issue_comment.workflow`): 
    `handlePullRequestOpened` (a `pull_request` `opened` delivery) and
    `handleIssueCommentCreated` (an `issue_comment` `created` delivery
    mentioning `@<app_slug> review`). Both resolve user/repo, gate on
    LLM + sandbox config, resolve the per-user LLM config + the
    settings-driven sandbox ctx, and dispatch `reviewWorkflow` under
    the deterministic id. The comment adapter fetches PR state via the
    `github.pr` sub-service, adds the best-effort 👀 reaction, and sets
    `diffBaseSha` for an **incremental re-review** when the head moved
    since the latest successful `review` row.
  - `helpers.py` — pure comment-trigger logic: `validateCommentPayload`
    (typed projection onto `CommentTriggerInput`, `None` on malformed),
    `classifyComment` (`action` / `is_pr` / `is_self` / `has_mention` /
    `is_authorized` short-circuit), `effectiveDiffBase` (the
    incremental-re-review decision), `REVIEW_MENTION_RE`,
    `WRITE_ASSOCIATIONS`.
  - `types.py` — the serializable contract: `ReviewWorkflowCtx`
    (resolved LLM + sandbox environment), `ReviewWorkflowInput`,
    `RepoSnapshot`, `ReviewRunResult`, `ReviewLimits`, the `TotalUsages`
    / `TotalUsagesPerPR` token envelopes, plus the comment-trigger
    models `CommentTriggerInput` / `ClassifyCommentResult` /
    `LastReviewSnapshot`. Ids are branded types.
  - `errors.py` — error values (`ReviewStepError` + subclasses with a
    `retryable` flag) returned by pure step functions, the raised
    step-exception wrappers (`ReviewStepFailure` /
    `TransientReviewStepFailure`), and the `shouldRetry` /
    `isLlmRetryError` / `isRetryableStatusCode` predicates.
  - `steps/` — one file per I/O boundary, each exposing a pure worker
    and a DBOS-wrapped step: `get_repo`, `create_sandbox` (per-run
    **ephemeral** sandbox; no `sandboxes` row), `clone_repo` (mints an
    installation token, clones the default branch — token via `envs`,
    never argv — and best-effort fetches `refs/pull/{pr}/head` so
    fork-PR heads are diffable), `upsert_pr`, `review_lifecycle` (the
    durable `review` lifecycle-row steps), `fetch_diff`, `split_diff`
    (uploads + runs the split script, returns the `SplitDiffResult`
    summary), `invoke_agent` (the two parallel research lanes +
    `runExtractorLanes` / `combineLaneOutcomes`), `extract_result` (the
    structured extractor steps), `persist` (summary / comments / usage
    rows), `post_review` (inline GitHub post with its own retry policy +
    `updatePostBacklinksTx`), `kill_sandbox` (destroys the ephemeral
    sandbox in the workflow's `finally`).
  - `scripts/` — `split_diff.py`, the in-sandbox splitter (stdlib-only,
    uploaded as bytes, never imported on the host): writes `overview.md`
    and the per-file chunks into `splitted_diffs/` and prints the tiny
    `SplitDiffResult` summary JSON to stdout (`overview_written`,
    `files_changed`, `skipped` — no per-file line sets).
- `github/` — the GitHub service package (sub-services follow the §9
  pattern): `installation/`, `repo/`, `pr/`, `webhook/`, plus the
  private `client.py` App-auth client factory. The GitHub post-pipeline
  (posting a review + the DB back-link updates) lives in
  `workflows/review/steps/post_review.py`, built on the `pr`
  sub-service — the legacy `post_review.py` / `workflow.py` modules
  were removed.
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

Nine tables; UUID (string, `uuidToStr()`) primary keys, timestamps are
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
├── is_indexed        bool?         (mirror; flipped by indexing workflow terminal steps)
├── indexed_run_id    str?          (back-pointer to the latest IndexRun; server-side only)
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

review                       (per-run lifecycle row; one row per review_workflow run)
├── id                str  PK
├── user_id           str  index
├── repo_id           str  → repos.id  CASCADE
├── gh_repo_id        bigint
├── pr_id             str  → pull_requests.id  CASCADE
├── pr_number         int
├── commit_id         str            (head sha; no FK)
├── base_sha          str?
├── workflow_id       str  UNIQUE index  (the deterministic
│                                       `review:{repo_id}:{pr}:{head_sha[:7]}` id)
├── trigger           str            ('opened' | 'comment')
├── state             STARTING | RUNNING | SUCCESS | FAILED  index
├── comment_count     int?
├── github_review_id  bigint?        (back-link to the GitHub PR review)
├── error_name / error_message  str?
├── error_context     jsonb?         (agent failure context; see build_error_context)
├── sandbox_id        str?
├── llm_provider / llm_client / llm_model / llm_base_url  str?  (snapshot of the
│                                        resolved LLMConfig at run time;
│                                        llm_provider = config source
│                                        'system' | 'user'; llm_client =
│                                        provider from 'provider:model')
├── started_at / completed_at  timestamptz?
└── created_at / updated_at

code_comments
├── pr_id             str  → pull_requests.id  CASCADE
├── review_id         str? → review.id  CASCADE    (lifecycle row of the run)
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
├── review_id         str? → review.id  CASCADE    UNIQUE (lifecycle row of the run)
├── commit_id         str            UNIQUE (head sha; no FK)
├── github_review_id  bigint?        (back-link to the GitHub PR review)
├── summary           text
├── verdict           APPROVE | COMMENT | REQUEST_CHANGES
└── created_at

review_usages
├── id                str  PK
├── user_id           str  index
├── pr_id             str  → pull_requests.id  CASCADE
├── review_id         str? → review.id  CASCADE    (lifecycle row of the run)
├── pr_number         int
├── repo_id           str  → repos.id  CASCADE
├── review_summary_id uuid? → review_summaries.id  CASCADE
├── review_status     SUCCESS | FAILED
├── input_tokens / output_tokens / total_tokens  int
├── input_token_details  jsonb?     (cache_read / cache_creation)
├── llm_model_id / llm_provider / llm_base_url  str?  (snapshot of the
│                                        resolved LLMConfig at run time)
└── created_at / updated_at
```

Enums (Python and DB-checked): `PRStatus`, `CommentSeverity`,
`CommentSide`, `CommentState`, `ReviewVerdict`, `SandboxState`,
`ReviewRunStatus`, `ReviewState`. The relationship graph: `Repo` 1—N
`PullRequest`, `PullRequest` 1—N `CodeComment` and 1—1 `ReviewSummary`
(per commit), 1—N `ReviewUsage`; `Review` (the per-run lifecycle row)
1—N `CodeComment`, 1—1 `ReviewSummary` (per run) and 1—N `ReviewUsage`.

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
`removed` → delete rows; `pull_request.opened` →
`workflows.review.triggers.handlePullRequestOpened` (dispatches
`reviewWorkflow`); `issue_comment.created` →
`workflows.review.triggers.handleIssueCommentCreated` (dispatches
`reviewWorkflow`); `push` → `handle_push_event` (dispatches the
incremental indexing workflow for default-branch pushes — see the
indexing pipeline below);
everything else → 202 with a log line.

**Setup pipeline.** `POST /ai/repo/setup` (202) dispatches one
`setup_workflow` per new repo: `ensure_repo_and_sandbox_step` (writes the
`repos` + `sandboxes` rows) → `mint_installation_token_step` (GitHub
installation token, embedded in the authenticated clone URL for the
clone) → `git_clone_step` → `stop_setup_sandbox_step` in `finally`. The
router's GET endpoint polls DBOS status. When `index_after_setup=True`
(router sets it from `Settings.indexing_configured`) and indexing is
configured, the workflow fires off
`app.services.indexing.workflow.indexRepo` with the deterministic id
`index:{owner}:{repo}` and passes `local_repo_id=ctx.repo_id` so the
indexing run can flip the parent `repos.is_indexed` mirror.

**Indexing pipeline.** `POST /indexing/repo` (202) and the setup
auto-dispatch both start `indexRepo` under the deterministic id
`index:{owner}:{repo}` (so duplicate dispatches dedupe; the in-sandbox
`mode="overwrite"` write is a safe full rewrite). The terminal
`SUCCESS` / `ERROR` paths each call a best-effort mirror step from
:mod:`app.services.indexing.steps.update_repo`:
`mark_repo_indexed_success_step` flips `repos.is_indexed = true` +
sets `repos.indexed_run_id = <run_id>`; `mark_repo_indexed_error_step`
flips `is_indexed = false` while keeping `indexed_run_id` back-pointed
to the failed run for the dashboard's debugging surface area. The
public `/github/repos` endpoint reads `Repo.is_indexed` alongside
`Repo.github_repo_id` in one indexed `SELECT` and coerces
`None → False` at the boundary so the response shape is a strict
`bool`; the frontend `Repo` type carries `is_indexed: boolean` and
the dashboard's "Index" button only renders when
`is_configured && !is_indexed`.

**Incremental indexing pipeline.** GitHub `push` deliveries on the
repo's default branch dispatch `incrementalIndexRepo` under the
deterministic id `index:{owner}:{repo}:{head_sha[:7]}` (duplicate
deliveries of the same head SHA dedupe; distinct commits get distinct
runs). The adapter (`app.services.indexing.incremental.webhook`)
aggregates `added` / `removed` / `modified` across **all** commits in
the payload, skips when the repo has never completed a full index
(`is_indexed` falsy — the full index owns the bootstrap), and skips
`deleted` / `created` / non-default-branch pushes. The workflow then:

1. `deleteStaleChunksStep` — host-side LanceDB delete of the
   `removed + modified` files' chunks (no sandbox; `table.delete`
   with `file_name IN (...)` predicates chunked at 100 names).
2. When `added + modified` is non-empty — a **fresh** index sandbox,
   authenticated clone URL → shallow clone → upload scripts →
   `incremental_ingestion.py` appends chunks for the explicit file
   list (never `mode="overwrite"`) and rebuilds the FTS index
   (`create_fts_index(replace=True)`).
3. `SUCCESS` mirrors keep `is_indexed = true` with
   `indexed_run_id` back-pointed; **`ERROR` mirrors never flip
   `is_indexed`** — the dataset still exists and remains searchable,
   only a few files are stale until the next successful push.

Both the full and incremental runs record one row in `index_runs`
(each `workflow_id` is unique), so the dashboard lists them
indistinguishably.

**Review pipeline.** Two triggers dispatch `reviewWorkflow`:

1. GitHub `pull_request` `opened` webhook →
   `workflows/review/triggers.handlePullRequestOpened` (validates,
   resolves user + repo, gates config, resolves the per-user LLM
   config, builds the settings-driven sandbox ctx).
2. A PR comment mentioning `@<app_slug> review` →
   `workflows/review/triggers.handleIssueCommentCreated` (classify →
   resolve → fetch PR state via the `github.pr` sub-service → resolve
   last review → 👀 → dispatch). The trigger resolves the latest
   successful `review` row for the PR (`loadLastReview`, filtering
   `state=SUCCESS`) and, when its head (`review.commit_id`) differs
   from the fetched head, runs an **incremental re-review**: the inner
   input carries `diffBaseSha = <last reviewed head>` so only the
   commits pushed since the previous review are diffed. `diffBaseSha`
   never touches `baseSha` — the `pull_requests` and `review` rows keep
   the PR's true base. The pure gate logic lives in
   `workflows/review/helpers.py` (`validateCommentPayload` /
   `classifyComment` / `effectiveDiffBase`).

Both start the workflow with the deterministic id
`review:{repo_id}:{pr_number}:{head_sha[:7]}`, so duplicate deliveries for
the same head SHA do not re-run the agent. `review_workflow` then runs:

1. `resolve_repo_tx` — look up the `Repos` row (`@dbos_datasource.transaction`).
2. `create_review_sandbox_step` — create a fresh **ephemeral** E2B
   sandbox for this run (no `sandboxes` row; the run's
   `review.sandbox_id` records it). Only the sandbox **id** travels
   onward; each step reconnects.
3. `clone_repo_step` — mint an installation token, clone the default
   branch into the sandbox (token via `envs`, never argv), and
   best-effort fetch `refs/pull/{pr}/head` so fork-PR heads are
   diffable.
4. `upsert_pull_request_tx` — insert/update the `PullRequest` row.
5. `mark_review_is_running_step` — create (or reset on restart) the
   `review` lifecycle row in `RUNNING`, keyed by the deterministic
   `workflow_id` (unique index), with the PR link, sandbox, and LLM
   snapshot; returns the row id. The step is **durable**: retried 3x on
   transient DB failures and raises `ReviewRunUpdateError` otherwise.
6. `fetch_diff_step` — `git diff {diff_base_sha or base_sha}...head_sha`
   written to the sandbox (`file.diff`). `diff_base_sha` narrows the
   range on an incremental re-review; `base_sha` (the PR's true base)
   still lands on the `pull_requests` / `review` rows.
7. `split_diff_step` — upload `split_diff.py` into the sandbox and run it
   against `file.diff`; the script writes `overview.md` (the four-bucket
   paths-only gate document) and the per-file annotated chunks into
   `splitted_diffs/`, and prints the tiny `SplitDiffResult` summary JSON
   to stdout (`overview_written`, `files_changed`, `skipped` — no per-file
   line sets; exit-code contract: `0` success, `-1` transient
   runner dropout, `>0` final `DiffSplitError`). The summary is parsed by
   the shared `parse_split_summary` in `helpers.py`; the diff text itself
   never crosses the sandbox boundary.
8. `invoke_summary_agent_step` / `invoke_comments_agent_step` — the
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
9. `persist_review_summary_tx` + `persist_code_comments_tx` — one
   `ReviewSummary` row and one `CodeComment` row per draft,
   each carrying the run's `review_id` (the lifecycle row).
10. `persist_review_usage_tx` — one `ReviewUsage` row with aggregated token
    counts (success path; `review_status=SUCCESS`), carrying `review_id`.
11. `mark_review_is_stopped_step` — flip the `review` row to `SUCCESS`
    with the surviving comment count and the GitHub review id (from the
    inline post step, when it posted). Durable like the running step.
12. `kill_sandbox_step` — always, in a `finally`: destroys the ephemeral
    per-run sandbox (best-effort; a kill failure never masks the run's
    outcome).

Steps 2–5 run **inside** the `try`, so the `finally` sandbox kill also
covers a raising clone / `upsert_pull_request_tx` / running step. The `except`
block flips the `review` row to `FAILED` via
`mark_review_is_errored_step` (guarded by its own try/except so a
failure while recording the error never masks the original exception —
which is then re-raised) and re-raises. All three `mark_*` steps are
durable (`@DBOS.step`, `retries_allowed=True`, `max_attempts=3`,
`should_retry=_SHOULD_RETRY_TRANSIENT`) and raise
`ReviewRunUpdateError` on failure, so a persistent lifecycle-row
failure marks the workflow ERROR instead of silently leaving the row
stuck in `RUNNING`; the running step's find-or-create semantics keep
retries idempotent via the unique `workflow_id`.

The summary in `review_summaries.summary` is the `summarizer` agent's
markdown output (from its `SummaryResult` structured response), and the verdict is
recomputed deterministically in code by `verdict_for()` from the merged
severities (any P1 → `REQUEST_CHANGES`, else any P2/P3 → `COMMENT`, else
`APPROVE`).

If `post_to_github` is enabled (always true on the webhook path), the
workflow posts the review inline via `postReviewStep`
(`workflows/review/steps/post_review.py`): a DBOS step with its own
retry policy (429 / 5xx retried without re-running the LLM); terminal
4xx failures return `posted=False` and the local review completes
regardless. On success `updatePostBacklinksTx` writes the GitHub
review / comment ids back onto the `review` / `code_comments` rows.

**Diff parsing and comment-line validation.** GitHub's review-comments API
rejects (422) any inline comment whose `(file, line, side)` anchor is not in
the PR's diff. Two layers guard this:

1. **Gutter-visible anchors (chunk-driven).** The comments agent reviews
   the per-file chunks under `splitted_diffs/`, each of which carries the
   visible LEFT/RIGHT gutter line numbers, so the agent anchors drafts only
   to lines it can see on its chosen side. (Prompt guidance for this is
   pending the agent redesign; the pipeline's split step already produces
   the chunks.)
2. **`< 1` guard.** `convert_to_github_comments` still rejects drafts with
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
  (`setup:{user_id}:{gh_repo_id}`, `index:{owner}:{repo}` for full
  indexing, `index:{owner}:{repo}:{head_sha[:7]}` for incremental
  indexing, `review:{repo_id}:{pr}:{head_sha[:7]}`, `post:{…}`) so
  duplicate deliveries dedupe and restarts are safe.
- **Workflow inputs declare canonical identifiers explicitly.**
  `IndexWorkflowInput.repo_owner` and `IndexWorkflowInput.repo_name` are
  client-supplied, Pydantic-validated, and read directly by the workflow
  and its steps — the panel no longer re-parses them off `repo_url`.
  The same convention applies to `SetupWorkflowInput`.
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
- Review pipeline (workflow + steps + agent fan-out) → `packages/api/src/app/workflows/review/`
- Comment-trigger logic (classify / validate / diff-base) → `packages/api/src/app/workflows/review/{helpers,triggers}.py`
- GitHub post workflow → `packages/api/src/app/services/github/`
- Setup workflow → `packages/api/src/app/services/setup/`
- Indexing pipeline (full + incremental) → `packages/api/src/app/services/indexing/`
- Per-user LLM config service + routes → `packages/api/src/app/services/llm_config/`, `packages/api/src/app/routers/llm_configs.py`
- Webhook receiver → `packages/api/src/app/routers/webhooks.py`
- Route tree → `web/src/routeTree.gen.ts` (generated)
- Pages → `web/src/routes/`
- API client + auth hooks → `web/src/lib/{api,auth,installation,repos,llm,stats}.ts`
- Env files → `ai-code-review/.env` (API), `web/.env` (Vite)

## 9. New Refactoring services patterns

The `app/services/{github,llm,sandbox}` packages are being refactored
into a shared service pattern. This section is the contract for those
packages (and any future service refactors); the older services
(`indexing`, `setup`) still follow the older conventions and will
migrate over time.

### 9.1 Package layout

Each service package owns one domain and lives under
`app/services/<name>/`:

- `types.py` — the contract: ctx models (identity + injected
  dependency), result projections, type aliases. Ids/keys are
  **branded types** from `app/utils/branded.py` (erase at runtime,
  enforced statically by pyright).
- `errors.py` — BaseModel error classes, one per sub-service.
- `service.py` — the entry points (camelCase, the camelCase island in
  the codebase). Every function takes a ctx and returns a value.
- `_client.py` — optional private module: the single node that builds
  the process-wide provider client (e.g. the githubkit App client)
  from settings. Never imported outside its package.
- Sub-domain services are their own subpackages, e.g.
  `github/installation/`, `github/repo/`, `github/pr/` — each with
  its own `types.py` / `errors.py` / `service.py` / `__init__.py`.

### 9.2 No unnecessary validation

- **Env vars are validated at app startup.** A startup function will
  fail the app when any required env var is missing — so services
  never gate on `*_configured` settings flags. Once settings load,
  the values are trusted.
- **Identity is validated upstream** (auth middleware, webhook
  receiver, caller). ctx creators are plain constructors — no
  existence or permission re-checks downstream.
- Functions check only what the function itself strictly needs to
  produce its own output (e.g. `postReview` requires `commitId`
  because the request body needs it).

### 9.3 No logging in services

Services do not import `logging`. They just return — success values
or error values. Logging (and Sentry capture) happens at the edge:
routers, webhook receivers, DBOS steps.

### 9.4 Errors are values, never exceptions

Expected failures are returned as BaseModel error classes (e.g.
`GitHubPRError`, `SandboxProviderError`, `LLMContextError`) in
`T | ErrorType` unions; callers discriminate with `isinstance`.
Raising is reserved for programmer/config errors (e.g. a missing
private key — which startup validation prevents).

### 9.5 ctx object dependency injection

- A ctx carries the identity a call needs plus its injected
  dependency (e.g. the installation-scoped githubkit `GitHub`
  client). Services consume `ctx.client`; they never build clients
  internally.
- **Deps live on the ctx unless it must serialize.** Attach injected
  dependencies (clients, providers, services) directly on the ctx —
  e.g. the installation-scoped githubkit client on `InstallationCtx` /
  `RepoCtx` / `PRCtx`. The one exception: a ctx that crosses a DBOS
  boundary (workflow input, step argument) **must** be serializable,
  so it stays pure data with no live deps (`SandboxCtx`, `LLMCtx`).
  Rule of thumb: if the ctx doesn't need to be serialized, its deps go
  on the ctx.
- The ctx **factory** is the I/O boundary ("edge"): `createRepoCtx`
  mints the client via the shared factory and stores it on the ctx.
- Ctxs carrying a live client are **not** serializable
  (`model_config = ConfigDict(arbitrary_types_allowed=True)`) and do
  not cross workflow boundaries; tests build them directly with mock
  clients. Ctxs that must cross DBOS boundaries stay pure data (see
  `SandboxCtx`, `LLMCtx`).
- App-level operations that a per-installation client cannot perform
  (token minting, installation fetch) use the process-wide client
  from the package's private `_client.py`.

### 9.6 I/O at the edge

- DB sessions are owned by the caller: functions that touch the DB
  take an `AsyncSession` parameter (e.g.
  `listInstallations(session, ctx)`).
- Logging, retries, and workflow dispatch belong to the edge
  (routers / webhooks / DBOS steps), not the service.

### 9.7 Status

- `github` — refactored: sub-services (`installation`, `repo`, `pr`,
  `webhook`), ctx-carried client, no gates, no logging. The legacy
  `post_review.py` / `workflow.py` modules were removed; posting now
  runs inline in `workflows/review/steps/post_review.py` via the `pr`
  sub-service.
- `llm` / `sandbox` — ctx-based services; `llm` drops env gates (env
  validated at startup), `sandbox` keeps its provider map + provider
  classes as the wiring seam. Both are built but not yet consumed by
  the pipeline.
