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
│       ├── alembic/
│       │   ├── env.py
│       │   └── versions/0001_init.py
│       └── src/app/
│           ├── main.py
│           ├── core/         # config, db, auth, middleware, workos, github
│           ├── models/       # SQLModel tables + enums
│           ├── schemas/      # (placeholder)
│           └── routers/      # health, auth, pipes, github, ai
└── web/                      # TanStack Start frontend (pnpm)
    ├── package.json
    ├── vite.config.ts
    ├── wrangler.jsonc
    ├── components.json       # shadcn/ui config (base-lyra, tabler)
    ├── tsr.config.json
    └── src/
        ├── router.tsx
        ├── routeTree.gen.ts
        ├── routes/           # file-based routes
        ├── components/       # layout + ui primitives
        ├── hooks/
        └── lib/              # api.ts, auth.ts, connections.ts, repos.ts, nav.tsx
```

Tooling posture: `uv` workspace for Python, `pnpm` for the web, `pyright`
configured at the root, `tsc` via Vite for the web, Alembic for schema
migrations. Python is pinned to 3.13. The API loads its environment from
`ai-code-review/.env` (the monorepo root), not from `packages/api/.env`.

## 2. System architecture

Three planes:

- **Web** — TanStack Start SPA, deployed to Cloudflare Workers. Owns the
  user-facing flows: sign-in, dashboard, repo selection, indexing kick-off.
- **API** — FastAPI monolith. Owns persistence, WorkOS integration, the
  GitHub client, and the (in-progress) AI review pipeline.
- **Integrations** — WorkOS for User Management (auth) and Pipes (data
  integrations). GitHub is reached *through* WorkOS Pipes, which mints and
  holds the GitHub OAuth tokens on Sentinel's behalf; the API exchanges a
  WorkOS user id for a fresh GitHub access token on every call.

Data flow at a glance:

1. Browser hits `/about`, clicks "Sign in with GitHub/Google".
2. WorkOS runs OAuth and 302s to `/api/auth/callback` with a code.
3. The API trades the code for tokens, seals a session into an httpOnly
   cookie, and 302s the browser to `/dashboard`.
4. From the dashboard, the user connects GitHub via `/api/pipes/connections/github/authorize`
   — another 302 → WorkOS Pipes → return to dashboard.
5. The API lists the user's repos by minting a GitHub token via Pipes and
   calling GitHubKit.
6. The user picks repos and POSTs them to `/api/ai/code/indexing`, which is
   the entry point for the review pipeline.

Postgres 18 is the only persistence tier, brought up by `docker-compose.yml`.

## 3. Backend — `packages/api`

### 3.1 Stack

- **FastAPI** on Python 3.13, async end-to-end
- **SQLModel** + **SQLAlchemy async** + **asyncpg** → PostgreSQL
- **Alembic** for migrations (asyncio runner)
- **pydantic-settings** for env-driven configuration
- **WorkOS SDK** (`AsyncWorkOSClient`) for User Management and Pipes
- **GitHubKit** for the typed GitHub REST client

### 3.2 Module map

`src/app/main.py` — application factory. Wires up `CORSMiddleware` with
`credentials=True` (sealed cookies must round-trip), then `AuthMiddleware`,
then registers routers under `settings.api_prefix`. The `lifespan` hook
runs `create_db_and_tables()` (which uses `SQLModel.metadata.create_all` —
useful for local dev; migrations are still the source of truth).

`src/app/core/`:

- `config.py` — `Settings(BaseSettings)` loaded from the monorepo-root
  `.env`. Exposes `workos_configured` and `cookie_secure` convenience
  properties. All env vars have safe defaults so the module can import in
  tests.
- `db.py` — async engine, `AsyncSessionLocal` sessionmaker, `get_session`
  dependency, `create_db_and_tables` for the lifespan hook.
- `auth.py` — defines the `Session` pydantic model (user_id, user_name,
  email, profile_picture, session_id, external_id, created_at, updated_at)
  and the `get_current_session` dependency that loads the sealed cookie
  and returns a 401 on any failure (missing cookie, decrypt failure,
  unauthenticated result, missing user_id/email, or missing session_id).
- `middleware.py` — `AuthMiddleware(BaseHTTPMiddleware)`. Skips
  `OPTIONS` requests (CORS preflight), then guards the path prefixes
  `/api/pipes`, `/api/github`, `/api/ai`. On success it attaches the
  full `Session` plus flat fields (`user_id`, `session_id`, `email`,
  `user_name`, `profile_picture`) to `request.state`. On failure it
  returns `{"detail": "Unauthorized"}` with status 401.
- `workos.py` — single-process lazy `AsyncWorkOSClient`. Wraps:
  - `get_authorization_url(provider)` — returns `(url, state)`; the
    router 302s to `url`.
  - `authenticate_code(code)` — async; exchanges the OAuth code for an
    `AuthenticateResponse`.
  - `seal_session(auth_response)` / `load_session(cookie_value)` —
    sync; uses `seal_session_from_auth_response` and
    `load_sealed_session` from WorkOS. Cookie payload is Fernet-sealed,
    so loading is local — no network IO.
  - `list_user_data_providers(user_id)`, `authorize_data_integration(...)`,
    `get_github_access_token(user_id)` — the Pipes surface used by
    `/pipes` and `/github` routers.
- `github.py` — `github_client_for(user_id)`: mints a GitHub access token
  via Pipes and returns a typed `githubkit.GitHub` client.

`src/app/services/`:

- `agent/` — the deep-agent graph and its subagents.
  - `models.py` — Pydantic response schemas (`CodeCommentDraft`,
    `ReviewResult`, `SetupResult`) emitted by the agents.
  - `prompts.py` — system prompts for the orchestrator and its four
    subagents: `summarizer` (PR summary, persisted as the review
    summary text), `security` (P1_CRITICAL only), `correctness`
    (P2_WARNING only), and `style` (P3_NITPICK only). Deliberately
    long and rubric-driven so each specialist has tight vocabulary.
  - `setup.py` — single-shot deep-agent that installs dependencies
    in the E2B sandbox before the review pipeline runs. No
    subagents; emits a `SetupResult`.
  - `setup_pipeline.py` — Functional Core / Imperative Shell that
    sequences installation-lookup, token-mint, `git clone`, and the
    setup agent.
  - `setup_errors.py` — typed error variants for the setup pipeline.
- `review/` — the review pipeline (the production target of the
  system).
  - `pipeline.py` — orchestrator + agent factory. Composes the
    single ``create_deep_agent`` graph and the four
    ``SubAgent`` specialists via
    ``assemble_review_subagents()``. ``run()`` sequences the I/O
    (repo, sandbox, diff, PR upsert, agent invoke, persistence) and
    returns a ``Result[ReviewRunResult, ReviewPipelineError]``.
  - `webhook.py` — GitHub ``pull_request`` ``opened`` adapter for
    the review pipeline. Owns the verified-payload → background-task
    handoff.
  - `types.py` — `ReviewRunResult` and the `DiffProvider` /
    `ReviewAgentRunner` ports.
  - `errors.py` — typed error variants for the review pipeline.

`src/app/models/`:

- `enums.py` — `PRStatus` (OPEN/CLOSED/MERGED), `AnalysisStatus`
  (PENDING/PROCESSING/COMPLETED/FAILED), `CommentSeverity`
  (P1_CRITICAL/P2_WARNING/P3_NITPICK), `CommentSide` (RIGHT/LEFT),
  `CommentState` (ACTIVE/OUTDATED/RESOLVED), `ReviewVerdict`
  (APPROVE/COMMENT/REQUEST_CHANGES). All `str, enum.Enum`.
- `repo.py` — `Repo`.
- `pull_request.py` — `PullRequest`.
- `commit_snapshot.py` — `CommitSnapshot`.
- `code_comment.py` — `CodeComment`.
- `review_summary.py` — `ReviewSummary`.
- `__init__.py` — re-exports every model so `from app.models import *`
  in `alembic/env.py` registers them on `SQLModel.metadata`.

`src/app/routers/`:

- `health.py` — `GET /health` → `{"status": "ok"}`. Unguarded.
- `auth.py` — `GET /auth/login?provider=`, `GET /auth/callback?code=`,
  `POST /auth/logout`, `GET /auth/session`. Provider slugs are mapped
  to WorkOS provider names (`google` → `GoogleOAuth`,
  `github` → `GitHubOAuth`). The callback 302s to
  `http://localhost:3000/dashboard` and sets the sealed cookie; note
  the `secure=True` flag is hard-coded, so a non-HTTPS callback will
  not work in production.
- `pipes.py` — `GET /pipes/connections` lists the user's connected data
  providers (slug, name, connected bool, connected_at). `GET
  /pipes/connections/{slug}/authorize` returns a 302 to WorkOS's
  authorize URL with `return_to = FRONTEND_URL + "/dashboard"`.
- `github.py` — `GET /github/repos` lists the authenticated user's repos
  (top 30, sorted by `updated`). Returns a typed `RepoOut`. Failures
  surface as a 502 so the web client can render a retry UI.
- `ai.py` — `POST /ai/code/indexing` accepts a payload of
  `{repos: [{id, full_name, html_url}]}` and currently acks with
  `{accepted: N}`. It is the entry point for the indexing pipeline and
  is intentionally minimal in its current state.

### 3.3 Domain model

Five tables; all UUID primary keys, all `gen_random_uuid()` defaults on
the DB side, all `uuid4()` defaults in Python. Timestamps are
`TIMESTAMP(timezone=True)` with `now()` server defaults. CASCADE
deletes are declared at the DB level; SQLModel relationships use
`passive_deletes=True` so the ORM doesn't try to fetch children when
deleting parents.

```
repos
├── user_id            str(128)
├── org_id             str(128)?          (nullable)
├── github_repo_id     bigint             UNIQUE
├── repo_name          str(255)
├── repo_owner         str(255)           UNIQUE(owner, name)
├── clone_url          str(1024)
├── github_installation_id  bigint
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

commit_snapshots
├── pr_id              uuid  → pull_requests.id  CASCADE
├── sha                str(64)            UNIQUE(pr_id, sha)
├── previous_reviewed_sha  str(64)?       (for incremental diffing)
├── analysis_status    PENDING|PROCESSING|COMPLETED|FAILED
├── error_message      text?
└── created_at

code_comments
├── pr_id              uuid  → pull_requests.id       CASCADE
├── commit_id          uuid  → commit_snapshots.id    CASCADE
├── github_comment_id  bigint?   (back-link to the comment posted on GitHub)
├── file_name          str(1024)
├── comment            text
├── severity           P1_CRITICAL | P2_WARNING | P3_NITPICK
├── from_line / to_line
├── side               RIGHT | LEFT
├── node_type          str(128)?   (free-form: function name, class, etc.)
├── state              ACTIVE | OUTDATED | RESOLVED
├── created_at / updated_at
└── INDEX (commit_id, file_name, state)  for the dashboard's "active
   comments on this file in this snapshot" lookup

review_summaries
├── pr_id              uuid  → pull_requests.id       CASCADE
├── commit_id          uuid  → commit_snapshots.id    CASCADE  UNIQUE
├── github_review_id   bigint?   (back-link to the GitHub PR review)
├── summary            text
├── verdict            APPROVE | COMMENT | REQUEST_CHANGES
└── created_at
```

The shape of `code_comments` mirrors GitHub's review-comment API: a line
range, a side (the new/old side of the diff), and a state that
Sentinel can update when the underlying diff changes. The
`github_comment_id` and `github_review_id` columns are the back-links
that let Sentinel reconcile its own records with what is actually
posted to GitHub.

The relationship graph: `Repo` 1—N `PullRequest` 1—N `CommitSnapshot`
1—N `CodeComment` and `CommitSnapshot` 1—1 `ReviewSummary`.

### 3.4 Request lifecycles

**Authentication.** `/auth/login?provider=github` returns a 302 to
WorkOS's authorize URL. WorkOS runs the OAuth dance and 302s to
`/auth/callback?code=…`. The callback calls `authenticate_code`,
seals the response, sets the cookie, and 302s to
`http://localhost:3000/dashboard`.

**Protected routes.** The middleware runs first on every non-OPTIONS
request whose path starts with `/api/pipes`, `/api/github`, or
`/api/ai`. It loads the sealed cookie, calls `authenticate()` (local
Fernet decrypt + JWT verify, no network IO), and on success populates
`request.state`. Failures return `{"detail": "Unauthorized"}` /
401. `/api/auth` and `/api/health` are intentionally outside the
guard list.

**GitHub connect.** `/pipes/connections/github/authorize` returns a
302 to WorkOS's authorize URL. After the user grants, WorkOS redirects
back to `FRONTEND_URL/dashboard`. The next call to
`/pipes/connections` reports the GitHub connection as `connected`.

**List repos.** `/github/repos` mints a GitHub access token for the
caller via WorkOS Pipes, instantiates a GitHubKit client, and returns
the first 30 repos sorted by `updated_at` as typed `RepoOut` objects.

**Indexing request.** The web dashboard POSTs the selected repos to
`/ai/code/indexing`. The current handler is an ack — it logs and
returns `{accepted: N}`. The pipeline that follows (snapshot creation,
code fetch, AI analysis, comment + summary writes, GitHub posting) is
not yet wired in this codebase.

**Review pipeline.** GitHub's `pull_request` `opened` (or
`synchronize`) webhook is verified and handed to
`app.services.review.webhook.handle_pull_request_opened`. That
function resolves the local `Repo` row from the installation, then
schedules a background `trigger_review` task. The task builds a
`pipeline.Input` and calls `pipeline.run`, which:

1. Looks up the `Repo` row and the active `Sandbox` row, then
   connects to the E2B sandbox.
2. Fetches the unified diff (`git diff base_sha...head_sha`).
3. Upserts the `PullRequest` row.
4. Builds the chat model and the review deep-agent graph. The graph
   has one orchestrator (the root deep-agent) and four `SubAgent`
   children registered in `assemble_review_subagents()`:
   `summarizer`, `security`, `correctness`, `style`.
5. Invokes the agent. The orchestrator's loop is: read the diff and
   surrounding code → delegate to the `summarizer` first (its
   markdown output becomes `ReviewResult.summary` verbatim) →
   delegate to the three severity-bucketed specialists (in parallel
   if appropriate) → collect + dedupe findings → pick the verdict
   from the severities present (any P1 → `REQUEST_CHANGES`, else
   any P2/P3 → `COMMENT`, else `APPROVE`).
6. Persists one `ReviewSummary` row (the summarizer's text + the
   verdict) and one `CodeComment` row per specialist finding.
7. Stops the sandbox (always, in a `finally`).

The summary that lands in `review_summaries.summary` is the
`summarizer` subagent's bullet output, not a paragraph written by
the orchestrator. Every bullet in the summary is grounded in a
`file:line` reference; the summarizer's prompt includes a
self-critique pass that drops any ungrounded bullet before
returning.

### 3.5 Migrations

`packages/api/alembic/versions/0001_init.py` is the only migration. It
creates the five tables exactly as modeled, including every unique
constraint, check constraint, and index. The schema is duplicated in
SQLModel for type-safe queries, and `alembic/env.py` imports all
models to keep `target_metadata` in sync. New schema changes go
through Alembic; the lifespan's `create_all` is a convenience for
greenfield dev, not a substitute.

## 4. Frontend — `web`

### 4.1 Stack

- **TanStack Start** — SSR-capable React framework with file-based
  routing; the route tree is auto-generated into
  `src/routeTree.gen.ts` via `tsr generate`.
- **React 19** + **Vite 8**
- **Tailwind CSS 4** via `@tailwindcss/vite`, with a custom `dark`
  variant on `.dark` in `styles.css`
- **shadcn/ui** in the `base-lyra` style, `tabler` icon library
  (configured in `components.json`)
- **TanStack Query** for server state, **TanStack Router Devtools** in
  the bottom-right corner during dev
- **Cloudflare Workers** as the deploy target, wired through
  `@cloudflare/vite-plugin` and `wrangler.jsonc`
- **Geist** and **Geist Mono** variable fonts

### 4.2 Module map

- `src/router.tsx` — `getRouter()` returns a TanStack Router with
  scroll restoration and `defaultPreload: 'intent'`.
- `src/routeTree.gen.ts` — generated; do not edit.
- `src/routes/__root.tsx` — the HTML shell. Injects a *blocking*
  theme init script in `<head>` so the chosen theme is applied before
  paint, mounts a single `QueryClient`, wraps the app in
  `QueryClientProvider` + `TooltipProvider`, and renders the global
  `Toaster` and the TanStack devtools panel.
- `src/styles.css` — Tailwind v4 entry point with `@import "shadcn/tailwind.css"`,
  the OKLCH color tokens for the default (purple) theme, font
  declarations, and `@custom-variant dark (&:is(.dark *))`.
- `src/components/` — layout-level:
  - `app-sidebar.tsx` — the dashboard `Sidebar` (header with logo
    + Dashboard label, content from `navItems`, footer with
    `NavUser`).
  - `nav-main.tsx` / `nav-user.tsx` — sidebar section renderers.
  - `Header.tsx` / `Footer.tsx` — placeholders (Footer is empty).
  - `ThemeToggle.tsx` — three-state light/dark/auto toggle, persisted
    to `localStorage` under the key `theme`.
- `src/components/ui/` — the shadcn primitives in use: `sidebar`,
  `button`, `card`, `dialog`, `sheet`, `dropdown-menu`, `combobox`,
  `input`, `input-group`, `textarea`, `label`, `checkbox`,
  `switch`, `select`, `tabs`, `badge`, `avatar`, `popover`, `tooltip`,
  `breadcrumb`, `collapsible`, `scroll-area`, `separator`, `skeleton`,
  `button-group`, `item`, `sonner`.
- `src/lib/`:
  - `api.ts` — typed `fetch` wrapper. `apiBaseUrl` comes from
    `VITE_API_URL`. `credentials: "include"` is set on every call so
    the sealed session cookie flows. `ApiError` carries the status
    and body for typed error handling. Exports `apiClient` with
    `session`, `logout`, `connections`, `repos`, `startIndexing`.
  - `auth.ts` — `useSession` (TanStack Query against `/auth/session`),
    `protectPage` (used as `beforeLoad` on protected routes — calls
    `/auth/session`, redirects to `/about` on failure), `useLogout`.
  - `connections.ts` — `useConnections` query and a
    `getGithubConnection` selector that finds the entry with
    `slug === "github"`.
  - `repos.ts` — `useRepos` and `useStartIndexing` mutations.
  - `nav.tsx` — the dashboard nav config (Overview, Repositories,
    Reviews) using tabler icons.
  - `utils.ts` — `cn` helper, the standard shadcn `clsx` + `twMerge`
    combo.
- `src/hooks/use-mobile.ts` — viewport detection used by the
  responsive sidebar.

### 4.3 Route tree

```
/                    index.tsx          (placeholder)
/about               about.tsx          (landing + sign-in CTAs)
/dashboard           route.tsx          (SidebarProvider + Outlet)
  /                 index.tsx          (overview, GitHubConnectionCard)
  /repositories     route.tsx          (list, select, "Start indexing")
```

`/dashboard/reviews` is referenced in the sidebar nav (`lib/nav.tsx`)
but the corresponding route file does not exist yet.

### 4.4 Page guards

Every `/dashboard/**` route declares `beforeLoad: protectPage`.
`protectPage` calls `/auth/session` once; if the call fails or the
session is empty, it throws `redirect({ to: "/about" })`, which
TanStack Router turns into a navigation away from the protected
page. The `about` page itself reads `useSession()` to decide whether
to render the sign-in CTAs or an "Open dashboard" link.

### 4.5 Theming

`ThemeToggle` and the init script in `__root.tsx` are the two halves
of theming. The init script is intentionally injected as a raw
`<script>` so the theme is set before React mounts — this avoids the
flash-of-wrong-theme on first paint. The toggle cycles
`light → dark → auto → light` and persists the chosen mode to
`localStorage` under `theme`. The CSS side defines the color tokens
in `:root` and the `.dark` selector.

### 4.6 Data flow

- `GithubConnectionCard` (used on the dashboard overview and
  repositories pages) reads `/pipes/connections`, finds the `github`
  entry, and either renders a "Connect" link (which 302s to
  `/pipes/connections/github/authorize` → WorkOS → back to dashboard)
  or a "Connected" badge.
- `RepositoriesPage` reads the same connection. Once connected, it
  switches to `ConnectedView`, which calls `useRepos()` and lets the
  user check off repos. "Start indexing" calls
  `useStartIndexing(repos)`, which POSTs to `/ai/code/indexing` and
  toasts the accepted count on success.
- `useLogout` clears the session query data, invalidates it, and
  invalidates the router so a re-render of `protectPage` redirects
  to `/about`.

## 5. Cross-cutting conventions

These come from the code itself and are enforced by the patterns
already in place.

- **Async end-to-end on the backend.** No sync DB calls, no sync
  WorkOS client. Even the loadable session is local-only because
  WorkOS's sealed cookies are Fernet-encrypted, not server-stored.
- **Auth is opt-in per route group.** `AuthMiddleware.PROTECTED_PREFIXES`
  is the single declaration of which path families require a session.
  New protected route groups should be added there, not as
  per-handler dependencies.
- **TanStack Query owns server state on the web.** No `useEffect`
  fetching; no Redux. The `ApiError` type is the contract for
  failure paths.
- **Cookies are sealed, not signed.** `secure=True` is hard-coded in
  `auth.py`; non-HTTPS callbacks will not work in production.
  `cookie_secure` is exposed in settings but not currently consumed
  by the router.
- **SQLModel is the source of truth for the schema.** Alembic
  migrations mirror it. `from app.models import *` in `alembic/env.py`
  is the registration trick that keeps `target_metadata` in sync.
- **CASCADE deletes live at the DB layer.** SQLModel relationships
  use `passive_deletes=True` so that when a parent is deleted via
  SQL, the ORM doesn't load every child to issue per-row deletes.
- **UUIDs default twice** — `gen_random_uuid()` on the DB and
  `uuid4()` in Python. This is intentional belt-and-braces.
- **Severity and verdict are enums, not free text.** `P1_CRITICAL /
  P2_WARNING / P3_NITPICK` for comments; `APPROVE / COMMENT /
  REQUEST_CHANGES` for reviews. The check constraints in
  `0001_init.py` enforce the same set at the DB level.
- **shadcn/ui style is `base-lyra`, icons are `tabler`.** These are
  pinned in `web/components.json`; new components should match.
- **API base URL is `VITE_API_URL`.** The web client adds the route
  suffix; the prefix is already part of the env var (e.g.
  `http://localhost:8000/api`).
- **All API calls send `credentials: "include"`.** The sealed cookie
  is the auth surface, so cross-origin calls must be allowed and
  credentialed.

## 6. Configuration surface

### 6.1 Backend (`packages/api`, loaded from monorepo-root `.env`)

| Variable | Default | Purpose |
| --- | --- | --- |
| `DATABASE_URL` | `postgresql+asyncpg://postgres:postgres@localhost:5432/aicode` | Async SQLAlchemy URL |
| `CORS_ORIGINS` | `["http://localhost:3000"]` | Allowed origins (JSON array in env) |
| `API_PREFIX` | `/api` | Prefix for every router registration |
| `WORKOS_API_KEY` | `""` | WorkOS API key |
| `WORKOS_CLIENT_ID` | `""` | WorkOS User Management client id |
| `WORKOS_REDIRECT_URI` | `http://localhost:8000/api/auth/callback` | Must match the value registered in the WorkOS dashboard |
| `WORKOS_COOKIE_PASSWORD` | `""` | ≥32 random chars; used to seal the session cookie. Rotation invalidates every session |
| `FRONTEND_URL` | `http://localhost:3000` | Where the callback 302s to after setting the cookie |
| `session_cookie_name` | `wos_session` | Name of the sealed cookie |
| `session_max_age_seconds` | `604800` | Cookie / session lifetime (7 days) |

`workos_configured` is `True` only when the three required WorkOS
values are set; the `/auth` router returns a 503 if it isn't.

### 6.2 Frontend (`web/.env`)

| Variable | Default | Purpose |
| --- | --- | --- |
| `VITE_API_URL` | — | Base URL for the API, including the API prefix (e.g. `http://localhost:8000/api`) |

## 7. Deployment shape

- **Web** targets Cloudflare Workers. `wrangler.jsonc` declares
  `compatibility_flags: ["nodejs_compat"]` and points the entry at
  `@tanstack/react-start/server-entry`. The Cloudflare Vite plugin
  is loaded in the SSR environment in `vite.config.ts`.
- **API** is a plain FastAPI app. There is no deploy configuration
  in this repository — bring your own host (containers, Fly,
  Railway, etc.). It expects Postgres 18 reachable at
  `DATABASE_URL` and WorkOS credentials in its env.

## 8. Where to find things

- Database schema → `packages/api/alembic/versions/0001_init.py`
- ORM models → `packages/api/src/app/models/`
- API routers → `packages/api/src/app/routers/`
- AI agent prompts (orchestrator + 4 subagents) → `packages/api/src/app/services/agent/prompts.py`
- AI agent response schemas → `packages/api/src/app/services/agent/models.py`
- Review pipeline (orchestrator + subagent factory + persistence) → `packages/api/src/app/services/review/pipeline.py`
- Setup agent (single-shot deep-agent) → `packages/api/src/app/services/agent/setup.py`
- WorkOS + GitHub plumbing → `packages/api/src/app/core/{workos,github,auth,middleware}.py`
- App wiring (middleware order, router registration) → `packages/api/src/app/main.py`
- Env loading → `packages/api/src/app/core/config.py`
- Route tree → `web/src/routeTree.gen.ts` (generated)
- Pages → `web/src/routes/`
- Shared UI → `web/src/components/ui/`
- API client → `web/src/lib/api.ts`
- Auth hooks + page guard → `web/src/lib/auth.ts`
- Theming → `web/src/components/ThemeToggle.tsx` and the init script in `web/src/routes/__root.tsx`
- Env files → `ai-code-review/.env` (API), `web/.env` (Vite)
