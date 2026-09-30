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
│   ├── api/                  # FastAPI backend (uv member)
│   │   ├── pyproject.toml
│   │   ├── alembic.ini
│   │   ├── main.py           # uvicorn entry point (packages/api/main.py)
│   │   ├── alembic/
│   │   │   ├── env.py
│   │   │   └── versions/     # 12 revisions
│   │   └── src/app/        # a README lives in every dir
│   │       ├── core/         # config, db, auth, middleware, workos, telemetry
│   │       ├── models/       # SQLModel tables + enums
│   │       ├── repositories/ # generic BaseRepository[T] + per-model subclasses
│   │       ├── routers/      # health, auth, github, ai, users, pulls,
│   │       │                 #   reviews, llm_configs, webhooks (+ schemas/)
│   │       ├── services/     # agent_v2/, github/, llm/, sandbox/
│   │       ├── workflows/    # durable/, review_v2/, triggers/
│   │       └── utils/        # branded ids, sandbox paths, agent schemas
│   └── evals/                # evaluation harness (uv member; see §3.8)
│       ├── main.py           # sequential runner: prepare → review → judge
│       ├── dataset/          # authored cases: {repo}-pr-{n}/{input,output}.json
│       ├── agents/           # review/ + judge/ (type, llm, prompt, agent)
│       ├── sandbox/          # shared sandbox: clone + diff + split artifacts
│       ├── results/          # per-PR review outputs (result.md)
│       └── report/           # per-PR judge reports (report.json)
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
  integration, the GitHub App client, the sandbox abstraction, and the
  durable review/repair pipelines (AWS Lambda Durable Execution).
- **Integrations** — WorkOS for auth (User Management; sealed session cookies),
  a native **GitHub App** for repo access (installation tokens minted
  server-side via `githubkit`'s `AppAuthStrategy`), **E2B** (default) or
  **Daytona** for sandboxed code execution, and any LangChain-supported LLM
  provider (`openai:…`, `anthropic:…`, `google_genai:…`, …) for the review
  agents.

Postgres 18 is the only persistence tier, brought up by `docker-compose.yml`.
Durable executions run on AWS Lambda (Durable Execution); execution state
is managed by Lambda, not Postgres.

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
   POSTs to `/api/ai/repo/setup` (200, synchronous bulk-insert of one
   `repos` row per repo).
7. GitHub webhook deliveries (verified by `X-Hub-Signature-256`) land on
   `POST /api/webhooks/github` and drive the durable review functions:
   `pull_request` `opened` Invokes `reviewOpenedHandler` and
   `issue_comment` `created` (mentioning `@<app_slug> review`) Invokes
   `reviewCommentHandler`, both via `workflows/triggers/invoke.py`.

## 3. Backend — `packages/api`

### 3.1 Stack

- **FastAPI** on Python 3.13, async end-to-end
- **SQLModel** + **SQLAlchemy async** + **asyncpg** → PostgreSQL
- **AWS Lambda Durable Execution SDK** (`aws_durable_execution_sdk_python`)
  for durable review/repair functions (checkpointed `@durable_step`s,
  per-step `StepConfig` retries, deterministic `DurableExecutionName`s)
- **Alembic** for migrations
- **pydantic-settings** for env-driven configuration
- **WorkOS SDK** (`AsyncWorkOSClient`) for User Management
- **githubkit** (`AppAuthStrategy`) for the GitHub App REST surface
- **LangChain** (`init_chat_model`) + **deepagents** for the review agents

### 3.2 Module map

`main.py` (at `packages/api/main.py`, not `src/app/`) — the FastAPI
application. `create_app()` wires `CORSMiddleware` (`credentials=True`, so
sealed cookies round-trip), then `AuthMiddleware`, then registers the nine
routers under `settings.api_prefix` (`/api`), and instruments the app via
`instrument_fastapi(app)`. The `lifespan` hook runs
`create_db_and_tables()` (a `SQLModel.metadata.create_all` convenience for
greenfield dev, skipped on Lambda). The module-level `handler =
Mangum(app, lifespan="off")` is the Lambda entry point (API Gateway →
Mangum → ASGI).
OpenLLMetry telemetry (`app/core/telemetry.py::init_telemetry`) is
initialised at import time when `settings.telemetry_configured`
(`TRACELOOP_BASE_URL` / `TRACELOOP_API_KEY` present) and is the
single observability entry point: it wires **traces** via `Traceloop`
and **logs** via an OTel SDK `LoggingHandler` on the root logger, both
exported over the same OTLP endpoint (see §3.7). The FastAPI app
is instrumented in `create_app()` via
`app/core/telemetry.py::instrument_fastapi` (see §3.7). On
Windows, the `__main__` block runs uvicorn directly on `0.0.0.0` at
`settings.port`.

`src/app/core/`:

- `config.py` — `Settings(BaseSettings)` loaded from the monorepo-root
  `.env`. Groups: server (port, database_url, cors_origins, api_prefix),
  WorkOS (`workos_*`, `frontend_url`, `session_cookie_name`,
  `session_max_age_seconds`), sandbox (`sandbox_provider`, `e2b_*`,
  `daytona_*`), embeddings (`openai_api_key`), LLM (`llm_model` as a
  `"provider:model"` string, `llm_api_key`, `llm_base_url`,
  `llm_default_headers`, `llm_max_retries`, `llm_rate_limit_rps`),
  GitHub App (`github_app_*`), durable functions
  (`review_opened_function_name`, `review_comment_function_name`,
  `repair_durable_function_name`), GitHub webhook
  (`github_webhook_secret`), install
  flow (`github_install_state_secret`). Convenience
  properties: `workos_configured`, `sandbox_configured`,
  `llm_configured` (accepts provider-native env vars via a provider→env-key
  map), `github_app_configured`, `github_webhook_configured`,
  `github_install_state_effective_secret`, `github_app_install_url`,
  `cookie_secure`. All env vars have safe defaults so
  the module can import in tests.
- `db.py` — async engine + `async_session_maker`, `get_session` dependency,
  and `create_db_and_tables`. Workers open their own sessions via
  `async_session_maker()` and own their transactions; the durable
  `@durable_step` edges just `asyncio.run` them.
- `auth.py` — the `Session` pydantic model (user_id, user_name, email,
  profile_picture, session_id, external_id, created_at, updated_at,
  github_login) and `get_current_session` dependency: reads the cookie,
  `load_session` (local Fernet decrypt, no network IO), `session.authenticate()`,
  projects the user payload, extracts `github_login` from the
  `GitHubOAuth` connection's `connection_id`, and 401s on any missing field.
- `middleware.py` — `AuthMiddleware(BaseHTTPMiddleware)`. `PROTECTED_PREFIXES`
  = `/api/github`, `/api/ai`, `/api/users`, `/api/llm_config`,
  `/api/review`, `/api/pulls`. `BYPASS_PREFIXES` =
  `/api/github/setup` (GitHub calls it via a browser redirect with no
  session cookie); `BYPASS_METHODS` exempts `POST /api/review` (gated by
  `X-Eval-Token` instead). Skips `OPTIONS`; on success attaches the
  full `Session` plus flat fields (`user_id`, `session_id`, `email`,
  `user_name`, `profile_picture`) to `request.state`; on failure returns
  `{"detail": "Unauthorized"}` / 401.
- `workos.py` — single-process lazy `AsyncWorkOSClient`. Wraps
  `get_authorization_url(provider)` → `(url, state)`,
  `authenticate_code(code)`, `seal_session(auth_response)`, and
  `load_session(cookie_value)`. Session sealing/loading is local (Fernet),
  so no network IO on the hot path.
- `telemetry.py` — OpenLLMetry (`traceloop-sdk`) wiring, the single
  observability entry point: `init_telemetry()` (import-time init gated on
  `settings.telemetry_configured`; sets `TRACELOOP_TRACE_CONTENT` /
  `TRACELOOP_TELEMETRY` env, then `Traceloop.init(...)` with the
  SDK's anonymous telemetry disabled, followed by an OTel SDK
  `LoggerProvider` + `LoggingHandler` that routes stdlib `logging`
  to `<endpoint>/v1/logs`) and `instrument_fastapi(app)`
  (attaches `FastAPIInstrumentor` when telemetry is on).
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
- `ai.py` — `POST /ai/repo/setup`: sync bulk-insert of one `Repo` row
  per requested repo (`{repos: [{id, owner, name, installation_id}]}`,
  skips repos that already have a row). Shapes in
  `routers/schemas/ai.py`.
- `users.py` — user-scoped reads: `GET /users/repos` (configured `repos` rows)
  and `GET /users/stats` (`prs_reviewed`, `comments_issued`,
  `bugs_caught` = P1 comment count, all joined through `pull_requests` so
  another user's repos can never leak).
- `pulls.py` — live GitHub PR reads plus the local Sentinel mirror:
  `GET /pulls/{owner}/{repo}[/{number}[/commits|files|conversation|sentinel]]`.
- `reviews.py` — `GET /review` (run list) and `POST /review`, the
  eval-only sync trigger gated by `X-Eval-Token`.
- `llm_configs.py` — per-user LLM config: `POST /` (test-and-upsert), `POST
  /test` (probe only), `GET /` (stored row, `api_key` redacted). All return
  the `{data, success, error, test_result}` envelope with HTTP 200 so the
  frontend never branches on status. Shapes in
  `routers/schemas/llm_config.py`.
- `webhooks.py` — the GitHub App webhook receiver (see §3.5).

`src/app/services/`:

- `agent_v2/` — the review-agent layer (planning agent + per-file
  review agents, delegation disabled).
  - `types.py` — `AgentV2Ctx` (identity + live model/sandbox deps, never
    crosses the durable boundary) and the serializable `PlannerContext`
    / `FileContext` / `ChunkInventory` / `FileReviewJob`.
  - `prompts/` — one function per prompt: `planning.py` (planning rubric
    + `submit_plan` contract), `file_review.py` (single-chunk review
    rubric), `summary.py` (walkthrough synthesis), `shared.py`
    (comment-body contract, `NO_FINDINGS` marker, identity/PR-intent
    blocks, `getReviewDiffDirPath`, `SEARCH_CODEGRAPH_TOOL_DESCRIPTION`).
  - `service.py` — ctx factory + agent builders + the `submit_plan`
    tool mechanics + the `search_codegraph` tool (full query ladder
    over the run's codegraph DB, closed over the ctx; planner gets
    both tools, file agents get the search tool).
  - `_middleware.py` — private `NoDelegationMiddleware` (strips the
    `task` tool per model request) + the retry/limits stack.
  - `errors.py` — `AgentV2BuildError` (returned as a value, never raised).
- `workflows/durable/` — the durable functions: `opened_handler.py`
  (`reviewOpenedHandler`), `comment_handler.py`
  (`reviewCommentHandler`), `repair_handler.py`, the shared
  `pipeline.py` (`runAgentPhase`) / `repair_pipeline.py`
  (`runRepairPhase`) agent phases, flat `steps/` (one cohesive file
  per phase: `resolve`, `github`, `sandbox`, `agents`, `persist`,
  `repair` — each `@durable_step` validates its input model, runs
  one worker via `asyncio.run`, returns `model_dump`), plus
  `invoke.py` (best-effort async Lambda Invoke), `naming.py`
  (deterministic execution names), and `types.py` (strict
  event/result contract: `OpenedDurableEvent` /
  `CommentDurableEvent` / `DurableRepairEvent` in, `ReviewSkipped` /
  `ReviewCompleted` / `ReviewFailed` / `RepairSkipped` /
  `RepairCompleted` / `RepairFailed` out, plus the moved
  `CommentRow` / `UnpublishedReview` / `PublishedReview` repair
  models).
- `workflows/review_v2/` — the review worker library: planner +
  per-file review agents over shared infra workers.
  - `types.py` — the serializable contract: `ReviewWorkflowInput`,
    `RepoSnapshot`, `ReviewRunResult`, `ReviewLimits`, the `TotalUsages`
    / `TotalUsagesPerPR` token envelopes. Ids are branded types. (The
    trigger contract lives in `workflows/triggers/types.py`.)
  - `errors.py` — error values (`ReviewStepError` + subclasses with a
    `retryable` flag), the raised step exceptions
    (`ReviewStepFailure` / `TransientReviewStepFailure`), and the
    `isLlmRetryError` / `isRetryableStatusCode` classifiers.
  - `steps/` — one worker per pipeline phase, each raising
    `ReviewStepFailure` / `TransientReviewStepFailure`:
    `create_sandbox` (per-run **ephemeral** sandbox; no `sandboxes`
    row), `clone_repo_v2` (atomic clone: default-branch clone +
    PR-ref fetch + detached head checkout, fail-closed — token via
    inline `GITHUB_TOKEN` env, never argv), `upsert_pr`,
    `review_lifecycle` (the `review` lifecycle-row steps),
    `fetch_diff`, `split_diff` (uploads + runs the split script,
    returns the `SplitDiffResult` summary), `list_chunks`
    (inventories `splitted_diffs/` into the `ChunkInventory` diff
    truth), `invoke_planner` (planning-agent research + `plan.json`
    read-back), `invoke_file` (one scoped per-file lane, retried
    alone), `synthesize_summary` (walkthrough synthesis, degrades to
    empty), `combine` (pure join/merge: trivial filter, context join,
    report concat, `combineV2Reports` over the local `CombinedReview`
    / `combineReviewResults` / `verdictFor` merge rules),
    `extract_result` (the structured comments extractor), `persist`
    (summary / comments / usage rows), `post_review` (inline GitHub
    post with its own retry policy + `updatePostBacklinksTx`),
    `kill_sandbox` (destroys the ephemeral sandbox; never masks the
    outcome).
  - `scripts/` — `split_diff.py`, the in-sandbox splitter (stdlib-only,
    uploaded as bytes, never imported on the host): writes `overview.md`
    and the per-file chunks into `splitted_diffs/` and prints the tiny
    `SplitDiffResult` summary JSON to stdout (`overview_written`,
    `files_changed`, `skipped` — no per-file line sets).
- `workflows/triggers/` — the webhook edge adapters (pure extraction +
  one best-effort Invoke; no DB, no GitHub fetch):
  `invoke.py` (`handlePullRequestOpened` for `pull_request` `opened`,
  `handleIssueCommentCreated` for `issue_comment` `created` mentioning
  `@<app_slug> review`), `opened_payload.py` (`extractOpenedPrPayload`),
  `comment_payload.py` (pure comment-trigger logic:
  `validateCommentPayload`, `classifyComment`, `effectiveDiffBase`),
  `repair.py` (`triggerRepairAfterReview`, dispatched best-effort from
  the review pipeline when the inline post returns `posted=False`),
  `types.py` (trigger contract). All ctx resolution (user, repo, PR
  state, last review, LLM + sandbox) runs as checkpointed steps
  inside the durable handlers.
- `github/` — the GitHub service package (sub-services follow the §9
  pattern): `installation/`, `repo/`, `pr/`, `webhook/`, plus the
  private `client.py` App-auth client factory. The GitHub post-pipeline
  (posting a review + the DB back-link updates) lives in
  `workflows/review_v2/steps/post_review.py`, built on the `pr`
  sub-service.
- `llm/config/` — per-user `llm_configs` sub-service (no durable
  workflow): `testLLMConfig` (never raises; runs a `create_deep_agent`
  probe with a `response_format` pydantic schema — the same
  structured-output path the review agents use),
  `saveUserLLMConfig` (probe then upsert), `listUserLLMConfigs`.
  Types in `types.py` (`LLMConfigTestResultPublic` is the wire
  shape); `LLMConfigStoreError` in `errors.py`.

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

sandboxes                        (legacy: nothing references this model;
├── id                str  PK     the review pipeline uses per-run ephemeral
├── user_id           str         sandboxes, recorded only as review.sandbox_id)
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

review                       (per-run lifecycle row; one row per durable review run)
├── id                str  PK
├── user_id           str  index
├── repo_id           str  → repos.id  CASCADE
├── gh_repo_id        bigint
├── pr_id             str  → pull_requests.id  CASCADE
├── pr_number         int
├── commit_id         str            (head sha; no FK)
├── base_sha          str?
├── workflow_id       str  UNIQUE index  (the deterministic
│                                       `review-v2:{gh_repo}:{pr}:{head_sha[:7]}`
│                                       execution name)
├── trigger           str            ('opened' | 'comment')
├── state             STARTING | RUNNING | SUCCESS | FAILED  index
├── comment_count     int?
├── github_review_id  bigint?        (back-link to the GitHub PR review)
├── error_name / error_message  str?
├── error_context     jsonb?         (failure context recorded on FAILED runs)
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
`workflows/triggers/invoke.handlePullRequestOpened` (validates the
payload, Invokes the opened durable function); `issue_comment.created`
→ `workflows/triggers/invoke.handleIssueCommentCreated` (validates +
classifies, Invokes the comment durable function); `push` → accepted
without indexing (pipeline removed);
everything else → 202 with a log line.

**Setup pipeline.** `POST /ai/repo/setup` (200) synchronously
bulk-inserts one `repos` row per requested repo and returns the
per-repo outcome. No sandbox, no workflow, no polling.

**Review pipeline.** Two thin triggers Invoke two durable functions
(no DB, no GitHub fetch in the trigger — all ctx resolution runs as
checkpointed steps inside the handlers):

1. GitHub `pull_request` `opened` webhook →
   `workflows/triggers/invoke.handlePullRequestOpened` (pure
   `extractOpenedPrPayload`, deterministic
   `review-v2:{gh_repo}:{pr}:{head_sha[:7]}` execution name).
2. A PR comment mentioning `@<app_slug> review` →
   `workflows/triggers/invoke.handleIssueCommentCreated` (pure
   `validateCommentPayload` + `classifyComment`, delivery-suffixed
   execution name since the head SHA is unknown without a fetch).
   The handler fetches live PR state via the `github.pr` sub-service,
   loads the latest successful `review` row, and, when its head
   (`review.commit_id`) differs from the fetched head, runs an
   **incremental re-review**: the input carries `diffBaseSha = <last
   reviewed head>` so only the commits pushed since the previous
   review are diffed. `diffBaseSha` never touches `baseSha` — the
   `pull_requests` and `review` rows keep the PR's true base. The pure
   gate logic lives in `workflows/triggers/comment_payload.py`
   (`validateCommentPayload` / `classifyComment` /
   `effectiveDiffBase`).

Each handler validates its event once, resolves ctx with early
returns (`ReviewSkipped` on user/repo/PR/last-review misses), builds
one `ReviewWorkflowInput`, and runs the shared `runAgentPhase`
(`durable/pipeline.py`):

1. `createEphemeralSandbox` — a fresh sandbox for this run (no
   `sandboxes` row; the run's `review.sandbox_id` records it). Only
   the sandbox **id** travels onward; each step reconnects.
2. `upsertPrRow` — insert/update the `PullRequest` row.
3. `markReviewRunning` — find-or-create the `review` lifecycle row in
   `RUNNING`, keyed by the deterministic execution name (unique
   `workflow_id` index), with the PR link, sandbox, and LLM snapshot.
4. `clonePrHead` — atomic clone: default-branch clone + PR-ref fetch
   + detached head checkout, verify-gated. Fail-closed: any checkout
   refusal fails the run instead of reviewing a half-built tree.
   Past this step there is exactly one world: PR tree + PR diff.
5. `indexCodegraph` — `pip install` the published codegraph CLI
   (public PyPI, no tokens) + index of the PR-head tree
   (`--overwrite` for retry idempotency). Fail-closed: a dead search
   tool fails the run instead of reviewing without it.
6. `fetchPrDiff` — `git diff {diffBaseSha or baseSha}...headSha`
   written to the sandbox (`file.diff`). `diffBaseSha` narrows the
   range on an incremental re-review; `baseSha` (the PR's true base)
   still lands on the `pull_requests` / `review` rows.
7. `splitPrDiff` — upload `split_diff.py` and run it against
   `file.diff`; the script writes `overview.md` and the per-file
   annotated chunks into `splitted_diffs/`, and prints the tiny
   `SplitDiffResult` summary JSON to stdout (`overview_written`,
   `files_changed`, `skipped`; exit-code contract: `0` success, `-1`
   transient runner dropout, `>0` final). The summary is parsed by
   `parseSplitSummary`; the diff text itself never crosses the
   sandbox boundary.
8. `listDiffChunks` — inventories `splitted_diffs/` into the
   `ChunkInventory` diff truth (real paths + observed chunk files).
9. `runPlanner` + `readPlannerOutput` — the planning agent researches
   the repo + chunks (graph-first via the `search_codegraph` tool)
   and submits via the `submit_plan` tool; the plan is read back from
   `plan.json` into a `PlannerContext`. **Enrichment-only**: any
   planner failure degrades to an empty context, never fails the run.
10. `buildFileReviewJobs` (pure) — joins inventory (truth) with planner
    context (enrichment); trivial files dropped host-side.
11. `runFileBatch` — one scoped per-file lane per job, fanned out in
    sequential batches (one wave sharing one rate limiter). Each file
    agent carries the `search_codegraph` tool for blast-radius
    checks. Each file retries alone; failed files degrade to nothing.
    All lanes failed → the run fails.
12. `extractReviewComments` — transcribes the concatenated file reports
    into `CodeComment` drafts (structured extractor).
13. `synthesizeWalkthrough` — synthesizes the walkthrough summary from
    planner context + findings; degrades to empty, never fails the run.
14. `persistSummary` + `persistComments` — one `ReviewSummary` row and
    one `CodeComment` row per draft, each carrying the run's
    `review_id` (the lifecycle row).
15. `persistUsage` — one `ReviewUsage` row with aggregated token counts
    (`review_status=SUCCESS`), carrying `review_id`.
16. `postGithubReview` — posts the review inline (429 / 5xx retried
    without re-running the LLM; terminal 4xx returns `posted=False`
    and the local review completes regardless). When `posted=False`
    with comments to show, the pipeline dispatches the repair durable
    best-effort (`dispatchRepairFollowUp`). On success
    `updateGithubBacklinks` writes the GitHub review / comment ids
    back onto the `review` / `code_comments` rows.
17. `markReviewSucceeded` — flips the `review` row to `SUCCESS` with
    the surviving comment count and the GitHub review id.
18. `destroySandbox` — destroys the ephemeral per-run sandbox
    (best-effort; a kill failure never masks the run's outcome).

The `except` block issues two plain steps — `markReviewFailed` (noops
when the running step never completed) + `destroySandbox` — and
returns `ReviewFailed`. Retries come from per-step `StepConfig`
(`RETRY_3` for infra/persist, `RETRY_1` for degrade/batch steps);
the running step's find-or-create semantics keep retries idempotent
via the unique `workflow_id`.

The summary in `review_summaries.summary` is the synthesized walkthrough
markdown, and the verdict is recomputed deterministically in code by
`verdictFor()` in `steps/combine.py` from the merged
severities (any P1 → `REQUEST_CHANGES`, else any P2/P3 → `COMMENT`, else
`APPROVE`).

**Repair pipeline.** When the review post returns `posted=False`, the
pipeline dispatches the repair durable (`repair:{pr}:{head_sha[:7]}`).
`repair_handler` validates the event once and runs the shared
`runRepairPhase` (`durable/repair_pipeline.py`): `loadUnpublishedReview`
(early `RepairSkipped` when no unpublished summary/comments exist) →
resolve LLM + sandbox from the unpublished row → reuse the review
sandbox steps (`createEphemeralSandbox`, `clonePrHead`, `fetchPrDiff`,
`splitPrDiff`) → `deleteClonedRepo` → `runRepairAgent` (deepagent with
the `publish_to_github` tool; MAY FIX ONLY anchors, never content;
`None` when the agent publishes nothing) → `savePublishOutcome`
(writes posted ids, deletes never-posted rows) → `destroySandbox` →
`RepairCompleted`. The except block destroys the sandbox and returns
`RepairFailed`.

**Diff parsing and comment-line validation.** GitHub's review-comments API
rejects (422) any inline comment whose `(file, line, side)` anchor is not in
the PR's diff. Two layers guard this:

1. **Gutter-visible anchors (chunk-driven).** The comments agent reviews
   the per-file chunks under `splitted_diffs/`, each of which carries the
   visible LEFT/RIGHT gutter line numbers, so the agent anchors drafts only
   to lines it can see on its chosen side. (Prompt guidance for this is
   pending the agent redesign; the pipeline's split step already produces
   the chunks.)
2. **`< 1` guard.** `convertToGithubComments` (review) and
   `toGithubComments` (repair) still reject drafts with
   `from_line < 1` (or `to_line < 1`) as final defence-in-depth.

### 3.6 Migrations

`packages/api/alembic/versions/` holds the forward-only revisions
(starting at `0001_init` with the original tables). Schema changes go
through Alembic; the lifespan's `create_all` is a convenience for
greenfield dev, not a substitute.

### 3.7 OpenTelemetry observability (traces + logs)

OpenLLMetry (`traceloop-sdk`, wired in `app/core/telemetry.py`) is the
single observability entry point. When `settings.telemetry_configured`
(`TRACELOOP_BASE_URL` / `TRACELOOP_API_KEY` set — otherwise the SDK is
never initialised and all logs stay on the console), it exports two
signals over the same OTLP/HTTP pipeline, so any collector can ingest
them:

- **Traces.** The SDK auto-instruments LangChain + the provider
  SDKs, so every LLM call of the review agents (planner + file lanes +
  extractor/summary steps) becomes a `gen_ai` span with model, token usage, and
  latency — no call-site changes. The FastAPI app is instrumented via
  `opentelemetry-instrumentation-fastapi` (`instrument_fastapi(app)` in
  `create_app()`, skippable with `TELEMETRY_FASTAPI=false`).
  `TRACELOOP_TRACE_CONTENT`
  (default `true`) controls whether prompts / completions / embeddings are
  captured as span attributes; `TRACELOOP_DISABLE_BATCH` sends spans
  immediately (dev convenience). The SDK's own anonymous telemetry is
  disabled.
- **Logs.** The API logs through stdlib `logging` (plain console via
  `logging.basicConfig` in `main.py`). When telemetry is configured, an
  OTel SDK `LoggingHandler` is attached to the root logger, so every
  `log.info` / `log.error` call in the codebase becomes an OTel log
  record exported to `<endpoint>/v1/logs` with the same resource
  attributes (`service.name=sentinel`, `env=development`); `extra`
  kwargs on a call are surfaced as LogRecord attributes. Failures in
  the review path are logged with the full run context (PR, SHAs,
  user, LLM provider/model, workflow id) as standard log records.

### 3.8 Evaluation harness — `packages/evals`

A minimal two-stage sequential runner (`main.py <pr-id>`) that
evaluates the production review agents against authored datasets:

1. **review** — POST `input.json` to the production `POST /api/review`
   route (Invokes the opened durable function, gated by `X-Eval-Token`);
   adapt the typed response and render `results/<pr-id>/result.json`.
2. **judge** (`agents/judge/`) — an isolated structured-output LLM
   judge scores the review against `dataset/<pr-id>/output.json` (gold
   bugs) + the diff and writes `report/<pr-id>/report.json`
   (per-comment verdicts + derived precision/recall/F1/FP rate).

Datasets are authored as `dataset/{repo}-pr-{n}/{input,output}.json`
(input: repo URL/owner/name, PR number, base/head SHAs; output: gold
verdict + bugs with id, location, severity).

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
- **Durable work belongs in durable executions.** Routers only validate +
  dispatch; handlers checkpoint every I/O step via `ctx.step`, and
  transient errors are retried per-step via `StepConfig` retry strategies.
- **Execution names are deterministic and encode the domain**
  (`review-v2:{gh_repo}:{pr}:{head_sha[:7]}` for opened reviews,
  `review-v2:{gh_repo}:{pr}:{delivery}` for comment re-reviews,
  `repair:{pr}:{head_sha[:7]}` for repair runs) so duplicate deliveries
  dedupe and restarts are safe.
- **Step inputs are validated Pydantic models.** Each `@durable_step`
  validates its input model first, runs one operation, and returns
  `model_dump(mode="json")`. Handlers validate the event once at entry
  and the result once at exit — never `dict[str, Any]` in between.
- **LLM configuration is a frozen value object** (`LLMCtx`) resolved
  per-user at review time (`resolveActiveLlmCtx`, falling back to
  `createDefaultLLMContext`), consumed only through `createLLMModel`.
- **Sandbox access goes through `BaseSandbox`** (`deepagents` backend);
  the provider map in `services/sandbox/service.py` is the only place
  that imports the E2B/Daytona adapters.
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
| `E2B_API_KEY`, `E2B_TEMPLATE`, `E2B_CPU_COUNT`, `E2B_MEMORY_MB`, `E2B_TIMEOUT_S` | `""` / `code-interpreter-v1` / `2` / `2048` / `1200` | E2B sandbox defaults (`E2B_TEMPLATE` → pre-baked `SENTINAL_CODE_SANDBOX_TEMP` once built by CI) |
| `DAYTONA_API_KEY`, `DAYTONA_TEMPLATE` | `""` | Daytona adapter config |
| `LLM_MODEL` | `""` | `provider:model` string for the review agents |
| `LLM_API_KEY` / `LLM_BASE_URL` / `LLM_DEFAULT_HEADERS` | `""` / `""` / `{}` | Provider credential / gateway base URL / headers |
| `LLM_MAX_RETRIES` / `LLM_RATE_LIMIT_RPS` | `3` / `0.5` | SDK retries, client-side rate limit |
| `GITHUB_APP_ID` / `GITHUB_APP_CLIENT_ID` / `GITHUB_APP_CLIENT_SECRET` / `GITHUB_APP_SLUG` | `""` | GitHub App identity |
| `GITHUB_APP_PRIVATE_KEY` / `GITHUB_APP_PRIVATE_KEY_PATH` | `""` | App private key (base64 or PEM path) |
| `GITHUB_WEBHOOK_SECRET` | `""` | HMAC secret for `X-Hub-Signature-256` |
| `GITHUB_INSTALL_STATE_SECRET` | `""` | HMAC secret for install-flow state; falls back to `WORKOS_COOKIE_PASSWORD` |
| `REVIEW_OPENED_FUNCTION_NAME` / `REVIEW_COMMENT_FUNCTION_NAME` / `REPAIR_DURABLE_FUNCTION_NAME` | `""` | Lambda function names/ARNs for the three durable executions (webhook Invoke targets) |
| `TRACELOOP_BASE_URL` / `TRACELOOP_API_KEY` | `""` / `""` | OpenLLMetry OTLP/HTTP trace + log endpoint / bearer token (both empty → SDK never initialised) |
| `TRACELOOP_TRACE_CONTENT` / `TRACELOOP_DISABLE_BATCH` | `true` / `false` | Capture prompts/completions on spans / send spans immediately (dev) |
| `TELEMETRY_FASTAPI` | `true` | Instrument the FastAPI app (HTTP spans) when telemetry is configured |

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
  `DATABASE_URL` and the env vars above. Migrations are forward-only.
  Durable review/repair runs on AWS Lambda (`packages/api/template.yaml`:
  `ReviewOpenedFunction`, `ReviewCommentFunction`,
  `RepairDurableFunction`); the API invokes them async with a
  deterministic `DurableExecutionName`.

## 8. Where to find things

- FastAPI entry point → `packages/api/main.py`
- Settings / env surface → `packages/api/src/app/core/config.py`
- Database schema → `packages/api/alembic/versions/`
- ORM models → `packages/api/src/app/models/`
- API routers → `packages/api/src/app/routers/`
- GitHub services (client, install, repo, pr, webhook) → `packages/api/src/app/services/github/`
- Sandbox abstraction → `packages/api/src/app/services/sandbox/` (E2B template builders in `e2b_template.py`)
- LLM factory (`LLMCtx` + `createLLMModel`) → `packages/api/src/app/services/llm/`
- AI agent prompts → `packages/api/src/app/services/agent_v2/prompts/`
- AI agent response schemas → `packages/api/src/app/utils/schema.py`
  (`CodeCommentDraft`, `ReviewComments`, `ReviewResult`)
- Review pipeline (workflow + steps + agent fan-out) → `packages/api/src/app/workflows/review_v2/`
- Trigger adapters (payload extraction + durable Invoke) → `packages/api/src/app/workflows/triggers/{invoke,opened_payload,comment_payload,repair}.py`
- Comment-trigger logic (classify / validate / diff-base) → `packages/api/src/app/workflows/triggers/comment_payload.py`
- Repair pipeline (handler + steps + agent repair) → `packages/api/src/app/workflows/durable/{repair_handler,repair_pipeline}.py`, `packages/api/src/app/workflows/durable/steps/repair.py`
- GitHub post workflow → `packages/api/src/app/services/github/`
- Per-user LLM config service + routes → `packages/api/src/app/services/llm/config/`, `packages/api/src/app/routers/llm_configs.py`
- Route request/response shapes → `packages/api/src/app/routers/schemas/`
- Webhook receiver → `packages/api/src/app/routers/webhooks.py`
- Route tree → `web/src/routeTree.gen.ts` (generated)
- Pages → `web/src/routes/`
- API client + auth hooks → `web/src/lib/{api,auth,installation,repos,llm,stats}.ts`
- Env files → `ai-code-review/.env` (API), `web/.env` (Vite)

## 9. New Refactoring services patterns

The `app/services/{github,llm,sandbox}` packages follow a shared
service pattern. This section is the contract for those packages
(and any future service refactors).

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
or error values. Logging happens at the edge:
routers, webhook receivers, durable steps.

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
  `RepoCtx` / `PRCtx`. The one exception: a ctx that crosses a durable
  boundary (workflow input, step argument) **must** be serializable,
  so it stays pure data with no live deps (`SandboxCtx`, `LLMCtx`).
  Rule of thumb: if the ctx doesn't need to be serialized, its deps go
  on the ctx.
- The ctx **factory** is the I/O boundary ("edge"): `createRepoCtx`
  mints the client via the shared factory and stores it   on the ctx.
- Ctxs carrying a live client are **not** serializable
  (`model_config = ConfigDict(arbitrary_types_allowed=True)`) and do
  not cross workflow boundaries; tests build them directly with mock
  clients. Ctxs that must cross durable boundaries stay pure data (see
  `SandboxCtx`, `LLMCtx`).
- App-level operations that a per-installation client cannot perform
  (token minting, installation fetch) use the process-wide client
  from the package's private `client.py`.

### 9.6 I/O at the edge

- DB sessions are owned by the caller: functions that touch the DB
  take an `AsyncSession` parameter (e.g.
  `listInstallations(session, ctx)`).
- Logging, retries, and workflow dispatch belong to the edge
  (routers / webhooks / durable steps), not the service.

### 9.7 Status

- `github` — the sole GitHub surface: sub-services (`installation`,
  `repo`, `pr`, `webhook`), ctx-carried client, no gates, no logging.
  The legacy `core/github_app.py` + `core/install_state.py` modules
  were removed; `routers/github.py` consumes this package directly
  (install URL, repo list, setup callback), and posting runs inline
  in `workflows/review_v2/steps/post_review.py` via the `pr`
  sub-service.
- `llm` / `sandbox` — ctx-based services; `llm` drops env gates (env
  validated at startup), `sandbox` keeps its provider map + provider
  classes as the wiring seam. Both are consumed by the pipeline
  (triggers resolve ctxs; steps build models and providers from
  them). The legacy `core/llm.py` (`LLMConfig` + `build_chat_model`)
  was removed; `LLMCtx` + `createLLMModel` are the only factory.
