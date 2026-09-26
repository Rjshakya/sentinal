# github — the only way to talk to GitHub

App-auth client factory plus four sub-services. All GitHub access in
the codebase (routers, triggers, workflow steps) goes through this
package; nothing builds a githubkit client directly.
`__init__.py` re-exports the full surface.

## Layout

- `client.py` — private factory (never imported outside this
  package): `getAppGitHub` (process-wide singleton) and
  `getAuthenticatedGitHubClient(installationId)`.
- `installation/` — install flow + local state: ctx factory,
  signed install URL, `signState`/`verifyState`, installation fetch,
  local row list/forget. See its README.
- `repo/` — repo reads: paginated installation repo list, single
  repo fetch, owner/repo → installation-id fallback, token mint,
  authenticated clone URL.
- `pr/` — PR reads (state, pulls, commits, files, issue/review
  comments, reviews), `addReaction`, `postReview`, `postComment`.
- `webhook/` — delivery dispatch: `(event, action)` registry plus
  the concrete handlers (install mirror writes, PR/comment
  delegation).

## API

Entry points take a ctx and return `T | ErrorType` — e.g.
`listInstallationRepos(ctx)`, `getInstallation(ctx)`,
`getPrState(ctx)`, `handleWebhookEvent(payload)`. See each
sub-service README for its table.

## Notes

- Ctx factories mint the client; API calls use `ctx.client`,
  App-level calls (token mint, installation fetch) use the
  process-wide client from `client.py`.
