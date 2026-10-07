# Sentinel — AI Code Review

> An AI-powered GitHub pull-request reviewer that reads a developer's diff,
> posts inline comments anchored to specific lines (tagged by severity),
> and publishes a short prose review summary with an overall verdict at the
> top of the PR, so reviewers can triage and merge with confidence.

Sentinel is built as a small monorepo: a Python FastAPI backend, a
TanStack Start web client, and a single Postgres database. It integrates
with **WorkOS** for sign-in, a **GitHub App** for repo access, **E2B**
for sandboxed code execution, and any of **OpenAI / Anthropic /
Google** as the review LLM.

> Looking for the deep architecture reference? See [AGENTS.md](./AGENTS.md).

---

## Table of contents

- [What it does](#what-it-does)
- [Architecture](#architecture)
- [Tech stack](#tech-stack)
- [Repository layout](#repository-layout)
- [Quickstart](#quickstart)
- [Environment variables](#environment-variables)
- [Database](#database)
- [Development workflow](#development-workflow)
- [API surface](#api-surface)
- [Domain model](#domain-model)
- [Deployment](#deployment)
- [Troubleshooting](#troubleshooting)
- [References](#references)

---

## What it does

1. **Sign in** with Google or GitHub via WorkOS. A sealed session cookie
   identifies the user across calls.
2. **Install the Sentinel GitHub App** on the accounts or organizations
   you want reviewed. Sentinel keeps a local `installation` row keyed by
   `(user_id, github_installation_id)`.
3. **Pick repos** on the dashboard. Sentinel mints a short-lived
   installation token and lists every repo the App can see.
4. **Configure repos** — `POST /api/ai/repo/setup` bulk-inserts one
   `Repo` row per selected repo (skipping already-configured ones),
   synchronously. No sandbox involved.
5. **Open a PR** on a connected repo. GitHub's `pull_request`
   `opened` webhook hands the delivery to a **durable Lambda execution**
   that:
   - creates a fresh ephemeral sandbox and clones the repo at the
     PR head SHA (fail-closed),
   - indexes the tree with the codegraph and fetches the unified
     diff,
   - splits it in-sandbox into per-file annotated chunks (the gutter
     line numbers tell the agent which `(file, line, side)` anchors
     GitHub will accept),
   - runs a planning agent (repo context) plus one review agent per
     changed file,
   - persists a `ReviewSummary` and one `CodeComment` per draft,
   - and posts the review inline to GitHub (best-effort, own retry
     policy).
   A PR comment mentioning `@<app_slug> review` triggers an
   incremental re-review of just the commits since the last run.
6. **Triage** on GitHub: a short PR summary up top, inline comments
   tagged `P1_CRITICAL` / `P2_WARNING` / `P3_NITPICK`, and a verdict
   of `APPROVE` / `COMMENT` / `REQUEST_CHANGES`.

The review pipeline is **idempotent** — its execution name is
`review-v2:{gh_repo_id}:{pr_number}:{head_sha[:7]}`, so duplicate webhook
deliveries for the same head SHA do not re-run the LLM. Each I/O step
is checkpointed, so a retry resumes from the last completed step
without re-running the agent. When the inline post fails terminally,
a repair execution (`repair:{pr_number}:{head_sha[:7]}`) re-anchors
and publishes the saved review.

---

## Architecture

Three planes, one persistence tier:

```
┌──────────────────────────┐    ┌──────────────────────────┐
│  Web (TanStack Start)    │    │  Integrations            │
│  - Cloudflare Workers    │    │  - WorkOS (auth)         │
│  - React 19 + Vite 8     │    │  - GitHub App (repos)    │
│  - TanStack Query        │  │  - E2B (sandbox)         │
│  - shadcn/ui (base-lyra) │    │  - OpenAI / Anthropic /  │
└──────────┬───────────────┘    │    Google (LLM)          │
           │                    └────────────┬─────────────┘
           │ cookie-based session           │ typed SDKs
           ▼                                 ▼
┌──────────────────────────────────────────────────────┐
│  API (FastAPI, async)                               │
│  - /auth, /github, /ai, /users, /pulls, /review,    │
│    /llm_config, /webhooks, /health                  │
│  - Durable executions (Lambda, checkpointed steps)  │
│  - SQLModel + asyncpg → PostgreSQL 18               │
└──────────────────────────────────────────────────────┘
                           │
                           ▼
                  ┌─────────────────┐
                  │  PostgreSQL 18  │
                  │  (docker-compose)│
                  └─────────────────┘
```

Read flow for the dashboard:

1. Browser hits `/about`, clicks **Sign in with GitHub/Google**.
2. WorkOS runs OAuth and 302s to `/api/auth/callback?code=…`.
3. The API trades the code for tokens, seals a session into an
   `httpOnly` cookie, and 302s the browser to `/dashboard`.
4. The dashboard calls `/api/github/installation`. If the user has no
   install, it offers an **Install on GitHub** button.
5. Clicking it calls `/api/github/install-url` (which signs an HMAC
   state token carrying the WorkOS `user_id`), then opens
   `https://github.com/apps/<slug>/installations/new?state=…` in a new
   tab.
6. After the user accepts, GitHub redirects to `/api/github/setup`,
   which verifies the state, fetches the installation from GitHub,
   upserts the local `installation` row, and 302s back to
   `/dashboard?installation=success`.
7. `/dashboard/repositories` calls `/api/github/repos` (a live
   pass-through to `GET /installation/repositories`) and lets the user
   check off repos to **Configure** — which posts to
   `POST /api/ai/repo/setup`.

Read flow for a PR review:

1. GitHub's `pull_request` `opened` webhook fires
   `POST /api/webhooks/github` (an `issue_comment` mentioning
   `@<app_slug> review` triggers an incremental re-review instead).
2. The handler verifies the `X-Hub-Signature-256` HMAC, validates the
   payload, and async-Invokes the review Lambda with execution name
   `review-v2:{gh_repo_id}:{pr_number}:{head_sha[:7]}`.
3. The execution runs end-to-end with checkpointed steps: ctx resolve
   → sandbox create → clone → codegraph index → diff fetch → in-sandbox
   split (overview + per-file chunks) → `PullRequest` upsert → planner
   + per-file agents → persist summary + comments + usage → inline
   post → sandbox destroy.
4. The inline post is best-effort: terminal failures return
   `posted=False` and dispatch a repair execution that re-anchors and
   publishes the saved review.

---

## Tech stack

| Layer        | Tools                                                                              |
| ------------ | ---------------------------------------------------------------------------------- |
| Web          | TanStack Start, React 19, Vite 8, TanStack Query, TanStack Router, Tailwind v4, shadcn/ui (`base-lyra`, `tabler` icons), Vitest |
| API          | FastAPI, Python 3.13, SQLModel, SQLAlchemy async, asyncpg, Alembic, pydantic-settings |
| Auth         | WorkOS User Management (Google + GitHub OAuth), sealed session cookies (Fernet)   |
| GitHub       | Native GitHub App via `githubkit` (typed REST), HMAC-signed install flow, webhook receiver |
| Sandbox      | E2B — provider map (`Providers`) resolves the class per run ctx                    |
| AI           | `deepagents` (planning agent + per-file review agents, delegation disabled), LangChain chat models |
| Durable jobs | AWS Lambda Durable Execution — checkpointed `@durable_step`s, per-step `StepConfig` retries, deterministic `DurableExecutionName`s |
| Database     | PostgreSQL 18 (docker-compose), `gen_random_uuid()` defaults, CASCADE FKs           |
| Logging      | stdlib `logging` → OpenTelemetry logs over OTLP (console fallback)                |
| Telemetry    | OpenLLMetry (`traceloop-sdk`) — OTLP/HTTP traces for the review agents + FastAPI     |
| Deploy       | Web → Cloudflare Workers (`wrangler.jsonc`); API → AWS Lambda via SAM (`packages/api/template.yaml`, stack `sentinel-dev`, `us-east-1`) |

---

## Repository layout

```
ai-code-review/
├── pyproject.toml            # uv workspace root
├── docker-compose.yml        # Postgres 18
├── .env / .env.example       # backend env (loaded from repo root)
├── AGENTS.md                 # deep architecture reference
├── packages/
│   ├── evals/                # review-quality harness (uv member)
│   ├── codegraph/            # codegraph CLI, published to PyPI (`pip install sentinel-codegraph`)
│   └── api/                  # FastAPI backend (uv member)
│       ├── pyproject.toml
│       ├── alembic.ini
│       ├── template.yaml     # SAM: 4 image Lambdas + regional HttpApi + domain
│       ├── Dockerfile.lambda # container image for all 4 Lambda functions
│       ├── samconfig.toml    # stack `sentinel-dev`, `us-east-1`, managed ECR repos
│       ├── main.py           # uvicorn entry point
│       ├── alembic/
│       │   ├── env.py
│       │   └── versions/     # forward-only revisions
│       └── src/app/        # backend package (a README lives in every dir)
│           ├── core/         # settings, db, auth, middleware, workos, telemetry
│           ├── models/       # SQLModel tables + enums
│           ├── repositories/ # generic BaseRepository[T] + per-model subclasses
│           ├── routers/      # health, auth, github, ai, users, pulls, reviews, webhooks, llm_configs (+ schemas/)
│           ├── services/     # agent_v2, github, llm, sandbox (ctx DI, errors-as-values)
│           ├── workflows/    # durable, review_v2, triggers
│           └── utils/        # branded ids, sandbox paths, agent schemas, badges
└── web/                      # TanStack Start frontend (pnpm)
    ├── package.json
    ├── vite.config.ts
    ├── wrangler.jsonc
    ├── components.json       # shadcn/ui config
    ├── tsr.config.json
    └── src/
        ├── router.tsx
        ├── routeTree.gen.ts  # generated; do not edit
        ├── routes/           # /about, /dashboard(/repositories)
        ├── components/       # layout + ui primitives
        ├── hooks/
        └── lib/              # api.ts, auth.ts, installation.ts, repos.ts, search.ts, nav.tsx
```

Tooling posture: `uv` workspace for Python, `pnpm` for the web, `pyright`
configured at the root, `tsc` via Vite for the web, Alembic for
migrations. Python is pinned to 3.13 (`.python-version`). The API loads
its env from `ai-code-review/.env` (the monorepo root), not from
`packages/api/.env`.

---

## Quickstart

### Prerequisites

- **Python 3.13** (`.python-version` is the source of truth)
- **[uv](https://docs.astral.sh/uv/)** — Python package and workspace manager
- **Node.js ≥ 20** and **pnpm**
- **Docker** with Compose v2 (for Postgres)
- Accounts / API keys for: WorkOS, GitHub (App), E2B (or Daytona), and your LLM provider

### 1. Clone and bootstrap

```bash
git clone <this-repo> ai-code-review
cd ai-code-review
uv sync                       # resolves the whole workspace
pnpm --dir web install        # installs the web app
```

### 2. Bring up Postgres

```bash
docker compose up -d db
```

This exposes Postgres 18 on `localhost:5432` with the credentials
`postgres:postgres` and database `aicode` (see `docker-compose.yml`).

### 3. Configure environment

```bash
cp .env.example .env
# edit .env and fill in WORKOS_*, GITHUB_APP_*, E2B_*, LLM_*
```

See the [Environment variables](#environment-variables) section for the
full list and a description of each. The web app reads its own env
from `web/.env` (see `web/.env.example`).

### 4. Run database migrations

```bash
cd packages/api
uv run alembic upgrade head
```

This applies all 8 revisions in `packages/api/alembic/versions/`.

### 5. Start the API and the web app

In two terminals:

```bash
# terminal 1 — API on :8000
cd packages/api
uv run python main.py
# (or: uv run uvicorn main:app --reload --port 8000)
```

```bash
# terminal 2 — web on :3000
cd web
pnpm dev
```

Open <http://localhost:3000>. The **Sign in with GitHub** button on
`/about` will round-trip through WorkOS and land you on
`/dashboard`.

### Run the API in Docker (optional)

If you'd rather skip the local Python toolchain, the backend (Postgres,
Alembic migrations, FastAPI) runs end-to-end in Docker:

```bash
cp .env.example .env          # then fill in WORKOS_*, GITHUB_*, E2B_*, LLM_*
docker compose up -d --build
curl http://localhost:8000/api/health   # {"status":"ok"}
```

On first boot, the `migrate` compose service runs `alembic upgrade head`
against the `db` service; the `api` service only starts after
migrations finish. `DATABASE_URL` is rewritten by Compose to point at
the `db` service; the rest of the env comes from the repo-root `.env`
via `env_file`.

The web app is not containerised — run it on the host with
`pnpm --dir web dev` and point `VITE_API_URL` at
`http://localhost:8000/api`.

Re-run migrations manually:

```bash
docker compose run --rm migrate
```

---

## Environment variables

A single `.env` at the repo root is loaded by `app.core.config.Settings`
(via pydantic-settings) for local dev. The web reads `web/.env` independently.

Production does NOT use `.env`. Prod config is the Secrets Manager JSON
secret `sentinel-dev/app` (~38 keys): 30 keys bind via CloudFormation
dynamic resolves in `template.yaml` Globals; the large
`GITHUB_APP_PRIVATE_KEY` is fetched at RUNTIME via
`app/core/secrets.py:app_secrets()` (Lambda's 4KB env limit forbids it
as an env var); region resolves `explicit-arg → SECRET_STORE_REGION →
AWS_REGION → us-east-1`.

### Backend (`ai-code-review/.env`)

| Variable                              | Default                                     | Purpose |
| ------------------------------------- | ------------------------------------------- | ------- |
| `DATABASE_URL`                        | `postgresql+asyncpg://postgres:postgres@localhost:5432/aicode` | Async SQLAlchemy URL |
| `CORS_ORIGINS`                        | `["http://localhost:3000"]`                 | Allowed origins (JSON array in env) |
| `API_PREFIX`                          | `/api`                                      | URL prefix for every router registration |
| **WorkOS (sign-in)**                  |                                             | |
| `WORKOS_API_KEY`                      | `""`                                        | WorkOS API key |
| `WORKOS_CLIENT_ID`                    | `""`                                        | WorkOS User Management client id |
| `WORKOS_REDIRECT_URI`                 | `http://localhost:8000/api/auth/callback`   | Must match the value registered in the WorkOS dashboard |
| `WORKOS_COOKIE_PASSWORD`              | `""`                                        | ≥32 random chars; used to seal the session cookie. Rotation invalidates every session. |
| `FRONTEND_URL`                        | `http://localhost:3000`                     | Where the callback 302s to after setting the cookie |
| `SESSION_COOKIE_NAME`                 | `wos_session`                               | Name of the sealed cookie |
| **Sandbox provider**                  |                                             | |
| `SANDBOX_PROVIDER`                    | `e2b`                                       | Active provider tag: `e2b` or `daytona` |
| `E2B_API_KEY`                         | `""`                                        | E2B API key |
| `E2B_TEMPLATE`                        | `code-interpreter-v1`                       | E2B template name (pre-baked `SENTINAL_CODE_SANDBOX_TEMP` once built by CI) |
| `E2B_CPU_COUNT`                       | `1`                                         | vCPU count for new sandboxes |
| `E2B_MEMORY_MB`                       | `1024`                                      | Memory (MB) for new sandboxes |
| `E2B_TIMEOUT_S`                       | `600`                                       | Timeout (seconds) for new sandboxes |
| `DAYTONA_API_KEY`                     | `""`                                        | Daytona API key (adapter kept for the day we swap back) |
| `DAYTONA_TEMPLATE`                    | `""`                                        | Daytona image name |
| **LLM (review + setup agents)**       |                                             | |
| `LLM_MODEL`                           | `""`                                        | `provider:model` string (e.g. `openai:gpt-5.5`, `anthropic:claude-opus-4-6`, `google_genai:gemini-3.6-flash`) consumed by `init_chat_model`. Leave empty to disable review routes. |
| `LLM_API_KEY`                         | `""`                                        | API key for the review/setup agent's chat model. Falls back to the provider's native env var (`OPENAI_API_KEY` / `ANTHROPIC_API_KEY` / `GOOGLE_API_KEY`) when blank. |
| `LLM_BASE_URL`                        | `""`                                        | Optional base URL for OpenAI-compatible proxies / gateways (Cloudflare AI Gateway, OpenCode Zen, Baseten, OpenRouter, Ollama, …). |
| `LLM_DEFAULT_HEADERS`                 | `{}`                                        | Optional JSON-encoded dict of HTTP headers attached to every LLM request (gateway IDs, project tags). |
| `LLM_MAX_RETRIES`                     | `3`                                         | Number of SDK retries on transient errors. |
| `LLM_RATE_LIMIT_RPS`                  | `0.5`                                       | Client-side requests-per-second rate limit (via `InMemoryRateLimiter`). Set `0` to disable. |
| `OPENAI_API_KEY`                      | `""`                                        | OpenAI key; injected into the indexing sandbox and used as the env-var fallback for `LLM_MODEL=openai:…`. |
| **Telemetry (OpenLLMetry)**           |                                             | |
| `TRACELOOP_BASE_URL`                  | `""`                                        | OTLP/HTTP endpoint for trace + log export (e.g. `http://localhost:4318`); the SDK appends `/v1/traces` and logs export to `/v1/logs`. Works with Traceloop Cloud, a self-hosted OpenTelemetry collector, or any OTLP backend. Leave empty (with `TRACELOOP_API_KEY`) to disable telemetry. |
| `TRACELOOP_API_KEY`                   | `""`                                        | Bearer token for the OTLP endpoint (required for Traceloop Cloud, optional for self-hosted collectors). |
| `TRACELOOP_TRACE_CONTENT`             | `true`                                      | Capture prompts / completions / embeddings as span attributes; set `false` to keep message bodies out of the traces. |
| `TRACELOOP_DISABLE_BATCH`             | `false`                                     | Send spans immediately instead of batching (dev convenience). |
| `TELEMETRY_FASTAPI`                   | `true`                                      | Instrument the FastAPI app (one HTTP span per request) when telemetry is configured. |
| **GitHub App (repo access)**          |                                             | |
| `GITHUB_APP_ID`                       | `""`                                        | GitHub App numeric id |
| `GITHUB_APP_CLIENT_ID`                | `""`                                        | GitHub App OAuth client id |
| `GITHUB_APP_CLIENT_SECRET`            | `""`                                        | GitHub App OAuth client secret |
| `GITHUB_APP_SLUG`                     | `""`                                        | App slug (the human-readable URL segment) |
| `GITHUB_APP_PRIVATE_KEY`              | `""`                                        | Base64-encoded single-line PEM. Prod: secret-only, runtime-fetched via `app/core/secrets.py`, never a Lambda env var (4KB limit) |
| `GITHUB_APP_PRIVATE_KEY_PATH`         | `""`                                        | Declared in `Settings` but currently unread — the client resolves the key from the value / runtime secret instead |
| `GITHUB_WEBHOOK_SECRET`               | `""`                                        | Shared secret used to verify `X-Hub-Signature-256`. Leave empty to reject all webhook deliveries. |
| `GITHUB_INSTALL_STATE_SECRET`         | `""`                                        | HMAC secret used to sign the install-flow state token. Falls back to `WORKOS_COOKIE_PASSWORD`. |
| **Durable executions**                |                                             | |
| `REVIEW_OPENED_FUNCTION_NAME` / `REVIEW_COMMENT_FUNCTION_NAME` / `REPAIR_DURABLE_FUNCTION_NAME` | `""` | Lambda function names/ARNs for the three durable executions (webhook Invoke targets) |

### Frontend (`web/.env`)

| Variable               | Default                | Purpose |
| ---------------------- | ---------------------- | ------- |
| `VITE_API_URL`         | *(required)*           | Base URL for the API, **including the API prefix** (e.g. `http://localhost:8000/api`) |
| `VITE_GITHUB_APP_SLUG` | `reviewpr-bot`       | Display name for the GitHub App (used in copy; must match the `@<slug> review` mention contract) |

`workos_configured`, `llm_configured`, `sandbox_configured`,
`github_app_configured`, and `github_webhook_configured` are derived
properties on `Settings` — each route returns 503 when its dependency
isn't configured.

---

## Database

PostgreSQL 18 is the only persistence tier, brought up by
`docker-compose.yml` on port 5432. The volume `aicode_pg_data` keeps the
data across container restarts.

Migrations live in `packages/api/alembic/versions/` and are
forward-only (starting at `0001_init`).

After `alembic upgrade head` the schema has **nine** tables: `repos`,
`pull_requests`, `code_comments`, `review_summaries`, `sandboxes`
(legacy, unreferenced), `installations`, `llm_configs`, `review`,
`review_usage`. The `commit_id` columns on `code_comments` and
`review_summaries` are plain strings (no FK).

Operations:

```bash
cd packages/api
uv run alembic upgrade head         # apply all
uv run alembic current               # show current revision
uv run alembic history --verbose     # show the chain
uv run alembic downgrade -1          # roll back one
```

`SQLModel.metadata.create_all` is called once at lifespan startup
(useful for greenfield dev). Alembic migrations are the source of
truth for schema changes — never edit them after they've been applied
to a shared environment.

The seven persisted entities are described in the
[Domain model](#domain-model) section.

---

## Development workflow

### Run the API

```bash
cd packages/api
uv run python main.py
# or, with auto-reload:
uv run uvicorn main:app --reload --port 8000
```

The first `docker compose up -d db` must already be running. Then
`uv run alembic upgrade head` once.

### Run the web app

```bash
cd web
pnpm dev
```

This starts Vite on `http://localhost:3000`. The `beforeLoad` guard on
every `/dashboard/**` route calls `/api/auth/session` and 302s to
`/about` if no session is present.

### Useful checks

```bash
# API health
curl http://localhost:8000/api/health

# regenerate TanStack Router types
cd web && pnpm generate-routes

# web tests
cd web && pnpm test

# pyright (Python)
uv run pyright
```

### Adding a new API route

1. Add the handler under `packages/api/src/app/routers/<area>.py`
   (request/response shapes go in `routers/schemas/<area>.py`).
2. Register it in `packages/api/main.py` under `settings.api_prefix`.
3. If the route requires auth, make sure the path starts with one of
   `AuthMiddleware.PROTECTED_PREFIXES` — add the new prefix there if
   needed.
4. Add / update Alembic migrations if the schema changed.

### Adding a new web route

1. Drop a file in `web/src/routes/`. TanStack Router auto-discovers
   it; run `pnpm generate-routes` to refresh `routeTree.gen.ts`.
2. If the route should be authenticated, export
   `beforeLoad: protectPage` from the route.

---

## API surface

All routes are mounted under `settings.api_prefix` (default `/api`).

| Method   | Path                                  | Auth          | Purpose |
| -------- | ------------------------------------- | ------------- | ------- |
| `GET`    | `/health`                             | none          | Liveness probe. Returns `{"status":"ok"}`. |
| `GET`    | `/auth/login?provider={github,google}`| none          | 302 to WorkOS authorize URL. |
| `GET`    | `/auth/callback?code=…`               | none          | Trades the code, sets the sealed cookie, 302s to `/dashboard`. |
| `POST`   | `/auth/logout`                        | none          | Clears the sealed cookie (204). |
| `GET`    | `/auth/session`                       | optional      | Returns the current `Session` or 401. |
| `GET`    | `/github/installation`                | required      | Lists every installation the signed-in user has. |
| `GET`    | `/github/repos`                       | required      | Live pass-through to `GET /installation/repositories` across all installations. |
| `GET`    | `/github/install-url`                 | required      | Mints a server-signed GitHub App install URL. |
| `GET`    | `/github/setup`                       | **bypass**    | GitHub's redirect target after install. Verifies HMAC state, upserts the local `installation` row, 302s to dashboard. |
| `DELETE` | `/github/installation/{installation_id}` | required   | Local "forget". Deletes the row. User still has to uninstall the App on github.com. |
| `POST`   | `/ai/repo/setup`                      | required      | Bulk-inserts one `Repo` row per requested repo (skips configured ones). Synchronous, no sandbox. |
| `GET`    | `/users/repos`                        | required      | Lists configured repos owned by the signed-in user. |
| `GET`    | `/users/stats`                        | required      | Dashboard stats: PRs reviewed, comments issued, P1 bugs caught. |
| `GET`    | `/pulls/{owner}/{repo}[/{number}[...]]` | required    | Live GitHub PR reads (list, detail, commits, files, conversation) plus the local Sentinel mirror (`.../sentinel`). |
| `GET`    | `/review`                             | required      | Lists review runs. |
| `POST`   | `/review`                             | **eval token**| Eval-only sync review trigger (header `X-Eval-Token`). |
| `POST`   | `/llm_config/`                        | required      | Probes a candidate LLM config, upserts on success. Always 200 with a `{data, success, error, test_result}` envelope. |
| `POST`   | `/llm_config/test`                    | required      | Probes without persisting. Same envelope minus `data`. |
| `GET`    | `/llm_config/`                        | required      | Stored configs with `api_key` redacted. |
| `POST`   | `/webhooks/github`                    | **HMAC**      | Receives `ping` / `installation` / `installation_repositories` / `pull_request` / `issue_comment` / `push` deliveries. Verified via `X-Hub-Signature-256`. `pull_request` `opened` and `@<app_slug> review` comments dispatch `reviewWorkflowV2`. |

Protected prefixes (enforced by `AuthMiddleware`):
`/api/github`, `/api/ai`, `/api/users`, `/api/llm_config`,
`/api/review`, `/api/pulls`. Bypass list: `/api/github/setup`
(GitHub calls it via user-agent redirect with no session cookie) and
`POST /api/review` (gated by `X-Eval-Token` instead).

---

## Domain model

Nine tables; string-UUID primary keys (`uuidToStr()`), `TIMESTAMP(timezone=True)`
timestamps with `now()` server defaults. CASCADE deletes are declared
at the DB layer; SQLModel relationships use `passive_deletes=True`.

```
repos
├── user_id            str(128)
├── org_id             str(128)?          (nullable)
├── github_repo_id     bigint             UNIQUE
├── repo_name          str(255)
├── repo_owner         str(255)           UNIQUE(owner, name)
├── clone_url          str(1024)
├── github_installation_id  bigint
├── url                str(1024)?         (html_url)
├── private            bool
├── default_branch     str(255)?
└── created_at / updated_at

installations
├── id                 uuid  PK
├── user_id            str(128)           index
├── github_installation_id  bigint        UNIQUE
├── account_login      str(255)
├── account_type       str(16)
├── repository_selection   str(16)
├── suspended_at       timestamptz?
└── created_at / updated_at

sandboxes
├── id                 uuid  PK
├── user_id            str(128)
├── repo_id            uuid  → repos.id  CASCADE
├── sandbox_name       str
├── state              STARTED|PAUSED|STOPPED|DELETED|ARCHIVED
├── provider_id        str?               ('e2b' | 'daytona')
├── started_at / stopped_at
└── created_at / updated_at

review
├── user_id            str                 index
├── repo_id            str  → repos.id    CASCADE
├── pr_id              str  → pull_requests.id  CASCADE
├── pr_number          int
├── commit_id          str                 (head sha; no FK)
├── base_sha           str?
├── workflow_id        str  UNIQUE index  (deterministic run id)
├── trigger            str?                ('opened' | 'comment')
├── state              STARTING|RUNNING|SUCCESS|FAILED
├── comment_count      int?
├── github_review_id   str?
├── error_name / error_message  str?
├── error_context      json?
├── sandbox_id         str?
├── llm_provider / llm_client / llm_model / llm_base_url  str?
└── started_at / completed_at + created_at / updated_at

pull_requests
├── repo_id            uuid  → repos.id  CASCADE
├── github_pr_id       bigint            UNIQUE
├── number             int               UNIQUE(repo_id, number)
├── author             str(255)
├── title              str(1024)
├── body               text?
├── status             OPEN|CLOSED|MERGED
├── base_branch / base_sha
├── head_branch / head_sha
└── created_at / updated_at

code_comments
├── pr_id              uuid  → pull_requests.id       CASCADE
├── review_id          str? → review.id  CASCADE
├── commit_id          uuid                             (head sha; no FK)
├── github_comment_id  bigint?    (back-link to GitHub)
├── file_name          str(1024)
├── comment            text
├── severity           P1_CRITICAL | P2_WARNING | P3_NITPICK
├── from_line / to_line
├── side               RIGHT | LEFT
├── node_type          str(128)?
├── state              ACTIVE | OUTDATED | RESOLVED
└── created_at / updated_at
   INDEX (commit_id, file_name, state)

review_summaries
├── pr_id              uuid  → pull_requests.id       CASCADE
├── review_id          str? → review.id  CASCADE
├── commit_id          uuid                          UNIQUE
├── github_review_id   bigint?    (back-link to GitHub)
├── summary            text
├── verdict            APPROVE | COMMENT | REQUEST_CHANGES
└── created_at

review_usages
├── user_id            str                 index
├── pr_id              str  → pull_requests.id  CASCADE
├── review_id          str? → review.id  CASCADE
├── pr_number          int
├── repo_id            str  → repos.id    CASCADE
├── review_status      SUCCESS | FAILED
├── input_tokens / output_tokens / total_tokens  int
├── input_token_details  json?           (cache_read / cache_creation)
├── llm_model_id / llm_provider / llm_base_url  str?
└── created_at / updated_at

llm_configs
├── user_id            str                 index
├── provider / model_id / base_url  str
├── api_key            str                 (redacted at the router)
└── created_at / updated_at
```

Enums (Python and DB-checked): `PRStatus`, `CommentSeverity`,
`CommentSide`, `CommentState`, `ReviewVerdict`, `SandboxState`,
`ReviewRunStatus`, `ReviewState`.

---

## Deployment

### Web (Cloudflare Workers)

The web is built and deployed to Cloudflare Workers. `wrangler.jsonc`
declares `compatibility_flags: ["nodejs_compat"]` and points the entry
at `@tanstack/react-start/server-entry`. The Cloudflare Vite plugin is
loaded in the SSR environment in `vite.config.ts`.

```bash
cd web
pnpm deploy    # = pnpm run build && wrangler deploy
```

Public (non-secret) env vars go in `wrangler.jsonc` under `vars`. For
secrets, use `wrangler secret put MY_VAR`.

### API (SAM → Lambda)

The API deploys via SAM (`packages/api/template.yaml`, stack
`sentinel-dev`, `us-east-1`) as 4 container-image Lambda functions:
`ApiFunction` (HTTP edge + webhook receiver) plus the three durable
workers `ReviewOpenedFunction`, `ReviewCommentFunction`, and
`RepairDurableFunction`. It expects:

- PostgreSQL 18 reachable at `DATABASE_URL` (use a managed Postgres or
  run a sidecar container).
- The Secrets Manager secret `sentinel-dev/app` holding every key in
  [Environment variables](#environment-variables) (30 keys bind via
  dynamic resolves; `GITHUB_APP_PRIVATE_KEY` is runtime-fetched).
  Template params: `AppSecretStore=sentinel-dev/app`,
  `SecretStoreRegion=us-east-1`. Never re-add a removed secret key
  without the add → deploy → remove dance — CloudFormation validates
  the OLD deployed model on update and fails on missing keys.
- `api.reviewpr.app` is served by the regional `HttpApi` +
  `ApiGatewayV2::DomainName` in the template (no CloudFront), with a
  DNS-only CNAME in Cloudflare pointing at the `ApiRegionalTarget`
  output.

Migrations are forward-only. Run `alembic upgrade head` before the
first deploy, and as part of every subsequent deploy that includes a
new revision.

### Production checklist

- Set `WORKOS_COOKIE_PASSWORD` to a fresh ≥32-char random string and
  keep it stable — rotating it invalidates every active session.
- Set `GITHUB_WEBHOOK_SECRET` (otherwise all deliveries are rejected).
- Set `GITHUB_INSTALL_STATE_SECRET` to a value independent of
  `WORKOS_COOKIE_PASSWORD` if you want to be able to rotate them
  separately.
- Restrict `CORS_ORIGINS` to the deployed web origin.

---

## Troubleshooting

- **"WorkOS is not configured" (503).** Fill in `WORKOS_API_KEY`,
  `WORKOS_CLIENT_ID`, and `WORKOS_COOKIE_PASSWORD` in `.env`.
- **"GitHub App is not fully configured" (503).** Set all of
  `GITHUB_APP_ID`, `GITHUB_APP_CLIENT_ID`, `GITHUB_APP_CLIENT_SECRET`,
  and `GITHUB_APP_SLUG`. `GITHUB_APP_PRIVATE_KEY` is also required by
  `get_app_github()`; the `github_app_configured` property currently
  treats it as optional.
- **Webhook deliveries return 401.** Either `GITHUB_WEBHOOK_SECRET` is
  unset or the secret in your GitHub App's webhook settings doesn't
  match.
- **Install button does nothing.** The `/github/install-url` call
  requires both the App config above and a non-empty
  `GITHUB_INSTALL_STATE_SECRET` (or `WORKOS_COOKIE_PASSWORD` as
  fallback).
- **`/api/ai/repo/setup` returns 503.** The review/setup LLM is not
  configured — set `LLM_BASE_URL`, `LLM_MODEL`, and `LLM_API_KEY` (or
  `OPENAI_API_KEY`).
- **No traces in the telemetry backend.** Set `TRACELOOP_BASE_URL` (and
  `TRACELOOP_API_KEY` for authenticated endpoints) in `.env` — with
  both empty the OpenLLMetry SDK is never initialised. For local
  debugging add `TRACELOOP_DISABLE_BATCH=true` to see spans in real
  time.
- **Database connection errors.** The `DATABASE_URL`
  (`postgresql://postgres:…@…/aicode`) must be reachable from the API
  host.

---

## References

- [AGENTS.md](./AGENTS.md) — deep architecture reference (present-tense
  description of the system, request lifecycles, design rationale).
- [`.env.example`](./.env.example) — annotated list of every backend
  env var.
- [`packages/api/alembic/versions/`](./packages/api/alembic/versions/) —
  the schema's source of truth.
- [`web/src/routeTree.gen.ts`](./web/src/routeTree.gen.ts) — generated
  TanStack Router route tree (do not edit; regenerate with
  `pnpm generate-routes`).
- [`docker-compose.yml`](./docker-compose.yml) — local Postgres 18.
