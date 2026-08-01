# Sentinel — AI Code Review

> An AI-powered GitHub pull-request reviewer that reads a developer's diff,
> posts inline comments anchored to specific lines (tagged by severity),
> and publishes a short prose review summary with an overall verdict at the
> top of the PR, so reviewers can triage and merge with confidence.

Sentinel is built as a small monorepo: a Python FastAPI backend, a
TanStack Start web client, and a single Postgres database. It integrates
with **WorkOS** for sign-in, a **GitHub App** for repo access, **E2B** (or
Daytona) for sandboxed code execution, and any of **OpenAI / Anthropic /
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
4. **Configure repos** — the synchronous setup agent clones the repo
   into an E2B sandbox, detects the package manager, installs
   dependencies, and records the bootstrap command.
5. **Open a PR** on a connected repo. GitHub's `pull_request` webhook
   hands the delivery to a **durable DBOS workflow** that:
   - resolves the local `Repo` row and the active sandbox,
   - fetches the unified diff,
   - parses it into a `HunkMap` (the source of truth for which
     `(file, line, side)` anchors GitHub will accept),
   - runs the review deep-agent (orchestrator + 4 specialist subagents:
     `summarizer`, `security`, `correctness`, `style`),
   - filters the agent's drafts through the `HunkMap` server-side,
   - persists a `ReviewSummary` and one `CodeComment` per surviving draft,
   - and — separately — posts the review to GitHub via a retryable
     workflow.
6. **Triage** on GitHub: a short PR summary up top, inline comments
   tagged `P1_CRITICAL` / `P2_WARNING` / `P3_NITPICK`, and a verdict
   of `APPROVE` / `COMMENT` / `REQUEST_CHANGES`.

The review pipeline is **idempotent** — its workflow id is
`review:{repo_id}:{pr_number}:{head_sha[:7]}`, so duplicate webhook
deliveries for the same head SHA do not re-run the LLM. A process
crash mid-invocation resumes from the last completed step without
re-running the agent.

---

## Architecture

Three planes, one persistence tier:

```
┌──────────────────────────┐    ┌──────────────────────────┐
│  Web (TanStack Start)    │    │  Integrations            │
│  - Cloudflare Workers    │    │  - WorkOS (auth)         │
│  - React 19 + Vite 8     │    │  - GitHub App (repos)    │
│  - TanStack Query        │    │  - E2B / Daytona (sandbox)│
│  - shadcn/ui (base-lyra) │    │  - OpenAI / Anthropic /  │
└──────────┬───────────────┘    │    Google (LLM)          │
           │                    └────────────┬─────────────┘
           │ cookie-based session           │ typed SDKs
           ▼                                 ▼
┌──────────────────────────────────────────────────────┐
│  API (FastAPI, async)                               │
│  - /auth, /github, /ai, /users, /webhooks, /health  │
│  - DBOS durable workflows                           │
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

1. GitHub's `pull_request` `opened` (or `synchronize`) webhook fires
   `POST /api/webhooks/github`.
2. The handler verifies the `X-Hub-Signature-256` HMAC, parses the
   payload, and dispatches a DBOS workflow with id
   `review:{repo_id}:{pr_number}:{head_sha[:7]}`.
3. The workflow runs end-to-end inside DBOS: diff fetch → parse →
   `PullRequest` upsert → review agent → `HunkMap` filter → persist
   summary + comments → sandbox stop.
4. A separate `post:{repo_id}:{pr_number}:{head_sha[:7]}` workflow
   posts the review to GitHub with retryable / non-retryable error
   handling.

---

## Tech stack

| Layer        | Tools                                                                              |
| ------------ | ---------------------------------------------------------------------------------- |
| Web          | TanStack Start, React 19, Vite 8, TanStack Query, TanStack Router, Tailwind v4, shadcn/ui (`base-lyra`, `tabler` icons), Vitest |
| API          | FastAPI, Python 3.13, SQLModel, SQLAlchemy async, asyncpg, Alembic, pydantic-settings |
| Auth         | WorkOS User Management (Google + GitHub OAuth), sealed session cookies (Fernet)   |
| GitHub       | Native GitHub App via `githubkit` (typed REST), HMAC-signed install flow, webhook receiver |
| Sandbox      | E2B (default) — Daytona adapter shipped alongside; pluggable via `BaseSandbox`     |
| AI           | `deepagents` orchestrator + 4 `SubAgent`s, LangChain chat models, `tree-sitter-language-pack` for parsing |
| Durable jobs | DBOS — durable workflows, idempotent steps, retryable transactions on the same Postgres |
| Database     | PostgreSQL 18 (docker-compose), `gen_random_uuid()` defaults, CASCADE FKs           |
| Logging      | JSON via `JsonFormatter` on the root logger                                         |
| Deploy       | Web → Cloudflare Workers (`wrangler.jsonc`); API → BYO host (containers, Fly, Railway, etc.) |

---

## Repository layout

```
ai-code-review/
├── pyproject.toml            # uv workspace root
├── docker-compose.yml        # Postgres 18
├── .env / .env.example       # backend env (loaded from repo root)
├── AGENTS.md                 # deep architecture reference
├── packages/
│   └── api/                  # FastAPI backend (uv member)
│       ├── pyproject.toml
│       ├── alembic.ini
│       ├── main.py           # uvicorn entry point
│       ├── alembic/
│       │   ├── env.py
│       │   └── versions/     # 8 migrations
│       └── src/app/
│           ├── core/         # config, db, auth, middleware, workos, github_app, llm, logging, sandbox/
│           ├── models/       # SQLModel tables + enums
│           ├── schemas/      # HTTP request/response shapes
│           ├── routers/      # health, auth, github, ai, users, webhooks
│           ├── repositories/ # generic Repository[T] base
│           ├── services/
│           │   ├── agent/        # deep-agent + subagent prompts/models + setup pipeline
│           │   ├── github/       # post-review to GitHub
│           │   └── review/       # DBOS durable workflow + steps + diff/hunk-map parsing
│           └── utils/        # uuidToStr, etc.
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
(via pydantic-settings). The web reads `web/.env` independently.

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
| `E2B_TEMPLATE`                        | `sentinel-indexing`                         | E2B template name |
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
| `LLM_LOG_IO`                          | `false`                                     | Emit per-LLM-call metadata JSON log lines for the review agents. |
| `OPENAI_API_KEY`                      | `""`                                        | OpenAI key; injected into the indexing sandbox and used as the env-var fallback for `LLM_MODEL=openai:…`. |
| **GitHub App (repo access)**          |                                             | |
| `GITHUB_APP_ID`                       | `""`                                        | GitHub App numeric id |
| `GITHUB_APP_CLIENT_ID`                | `""`                                        | GitHub App OAuth client id |
| `GITHUB_APP_CLIENT_SECRET`            | `""`                                        | GitHub App OAuth client secret |
| `GITHUB_APP_SLUG`                     | `""`                                        | App slug (the human-readable URL segment) |
| `GITHUB_APP_PRIVATE_KEY`              | `""`                                        | PEM private key; newlines may be encoded as the literal sequence `\n` |
| `GITHUB_APP_PRIVATE_KEY_PATH`         | `""`                                        | Filesystem path to the PEM. Takes precedence over `GITHUB_APP_PRIVATE_KEY`. |
| `GITHUB_WEBHOOK_SECRET`               | `""`                                        | Shared secret used to verify `X-Hub-Signature-256`. Leave empty to reject all webhook deliveries. |
| `GITHUB_INSTALL_STATE_SECRET`         | `""`                                        | HMAC secret used to sign the install-flow state token. Falls back to `WORKOS_COOKIE_PASSWORD`. |
| **DBOS**                              |                                             | |
| `DBOS_EXECUTOR_ID`                    | `socket.gethostname()`                      | Unique per running API instance |

### Frontend (`web/.env`)

| Variable               | Default                | Purpose |
| ---------------------- | ---------------------- | ------- |
| `VITE_API_URL`         | *(required)*           | Base URL for the API, **including the API prefix** (e.g. `http://localhost:8000/api`) |
| `VITE_GITHUB_APP_SLUG` | `ai-code-review`       | Display name for the GitHub App (used in copy) |

`workos_configured`, `llm_configured`, `sandbox_configured`,
`github_app_configured`, and `github_webhook_configured` are derived
properties on `Settings` — each route returns 503 when its dependency
isn't configured.

---

## Database

PostgreSQL 18 is the only persistence tier, brought up by
`docker-compose.yml` on port 5432. The volume `aicode_pg_data` keeps the
data across container restarts.

Migrations live in `packages/api/alembic/versions/`. The current
revision chain (oldest → HEAD), nine revisions total:

```
0001_init                                    # repos, pull_requests, commit_snapshots, code_comments, review_summaries
0002_extend_repos_and_sandboxes              # sandboxes table + extra repo columns
d2c05e88f8e9_drop_commit_snapshots_and_fix_fks
951a82befdb3_sandbox_provider_id_add         # sandboxes.provider_id
243a7473b750_add_indexing_status
d11be80b25c9_                                # installations table
5d1d3894e8a5_
fb1f0819aade_
efc8cecac0b4_                                # reposetupresult table  (HEAD)
```

After `alembic upgrade head` the schema has **seven** tables: `repos`,
`pull_requests`, `code_comments`, `review_summaries`, `sandboxes`,
`installations`, `reposetupresult`. The `commit_snapshots` table from
`0001_init` was dropped in `d2c05e88f8e9`; the `commit_id` columns on
`code_comments` and `review_summaries` are now plain strings (no FK).

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

`main.py` sets `WindowsSelectorEventLoop` for uvicorn on `win32` so
psycopg async / DBOS work on Windows. On Linux/macOS the default loop
is fine.

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

1. Add the handler under `packages/api/src/app/routers/<area>.py`.
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
| `POST`   | `/ai/repo/setup`                      | required      | Synchronous setup agent. Clones each repo into an E2B sandbox, detects ecosystem + package manager, installs deps, returns a per-repo `SetupResult`. |
| `GET`    | `/users/repos`                        | required      | Lists indexed repos owned by the signed-in user. |
| `POST`   | `/webhooks/github`                    | **HMAC**      | Receives `ping` / `installation` / `installation_repositories` / `pull_request` deliveries. Verified via `X-Hub-Signature-256`. `pull_request` `opened` / `synchronize` dispatches the durable review workflow. |

Protected prefixes (enforced by `AuthMiddleware`):
`/api/github`, `/api/ai`, `/api/users`. Bypass list: `/api/github/setup`
(GitHub calls it via user-agent redirect with no session cookie).

---

## Domain model

Seven tables; all UUID primary keys, all `gen_random_uuid()` defaults
on the DB side, all `uuid4()` defaults in Python (string ids —
`uuidToStr()`). Timestamps are `TIMESTAMP(timezone=True)` with `now()`
server defaults. CASCADE deletes are declared at the DB layer;
SQLModel relationships use `passive_deletes=True`.

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

reposetupresult
├── id                 uuid  PK
├── repo_id            uuid  → repos.id  CASCADE
├── user_id            str(128)           index
├── status             SUCCEEDED|FAILED
├── ok                 bool
├── ecosystem          str(16)            ('node' | 'python' | 'rust' | 'go' | 'ruby' | 'mixed' | 'none')
├── manager            str(128)?
├── install_cmd        str(1024)?
├── duration_s         float
├── notes              text
├── bootstrapped_tools text[]
├── error_code         str(64)?
├── error_message      text?
├── llm_provider       str(32)?
├── llm_model          str(128)?
├── sandbox_id         str(128)?
├── started_at / completed_at
└── created_at / updated_at

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
├── commit_id          uuid                             (no FK; commit_snapshots was dropped)
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
├── commit_id          uuid                          UNIQUE
├── github_review_id   bigint?    (back-link to GitHub)
├── summary            text
├── verdict            APPROVE | COMMENT | REQUEST_CHANGES
└── created_at
```

Enums (Python and DB-checked): `PRStatus`, `CommentSeverity`,
`CommentSide`, `CommentState`, `ReviewVerdict`, `SandboxState`,
`SetupRunStatus`, `SetupErrorCode`.

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

### API (BYO host)

The API is a plain FastAPI app — bring your own host (containers, Fly,
Railway, etc.). It expects:

- PostgreSQL 18 reachable at `DATABASE_URL` (use a managed Postgres or
  run a sidecar container).
- All the env vars listed in [Environment variables](#environment-variables).
- DBOS shares the same Postgres as the app (the `+asyncpg` driver
  suffix is stripped automatically — see `main.py::_dbos_config`).

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
- Pick a stable `DBOS_EXECUTOR_ID` per running instance when
  self-hosting multiple workers.

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
- **Sandbox create fails on Windows.** uvicorn must be using the
  `SelectorEventLoop`. `main.py` patches this in its `__main__` block
  for `sys.platform == "win32"`.
- **DBOS complains about the database URL.** The `+asyncpg` driver
  suffix is stripped for DBOS automatically. If you see connection
  errors, the rest of the URL (`postgresql://postgres:…@…/aicode`)
  must be reachable from the API host.

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
