# github/repo — reading repos from GitHub

Paginated repo listing, single-repo fetch, installation-token mint,
and authenticated clone-URL construction.

## Layout

- `service.py` — entry points (see API). `types.py` — `RepoCtx`
  (user + installation + owner/repo + client), `GitHubRepo` (flat
  repo projection). `errors.py` — `GitHubRepoError`.

## API

- `createRepoCtx(userId, installationId, owner, repo)` — ctx
  factory, mints the installation client. (`owner`/`repo` are only
  needed by single-repo calls; list callers pass empty brands.)
- `listInstallationRepos(ctx)` — every repo the installation can
  access, paginated at 100/page.
- `getRepo(ctx)` — single repo via `GET /repos/{owner}/{repo}`.
- `getInstallationIdForRepo(owner, repo)` — owner/repo →
  installation id fallback; `None` when the App isn't installed
  there.
- `mintAccessToken(ctx)` — fresh installation token (App client).
- `getCloneUrl(ctx, token)` — pure: authenticated https clone URL.

## Notes

- Used by `routers/github.py` (`GET /github/repos`) and the review
  clone step (`clone_repo_v2.py`: `createRepoCtx` + token mint).
