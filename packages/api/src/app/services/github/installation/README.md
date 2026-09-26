# github/installation — App install flow + local state

Owns the install round-trip (signed state token, install URL,
installation fetch) and the local `installations` mirror rows.

## Layout

- `service.py` — entry points (see API). `types.py` — `InstallationCtx`
  (user + installation id + client), `InstallationDetails` (flat
  install view), `InstallUrl`. `errors.py` —
  `GitHubInstallationError` (returned value, never raised).

## API

- `createInstallationCtx(userId, installationId)` — ctx factory,
  mints the installation client.
- `signState(userId, secret)` / `verifyState(token, secret)` —
  HMAC-signed state token carrying the WorkOS `user_id` through
  GitHub's install redirect (600s TTL; `verifyState` returns the
  user id or `None`).
- `getInstallUrl(userId)` — `https://github.com/apps/<slug>/…?state=…`.
- `getInstallation(ctx)` — installation details via the App client.
- `listInstallations(session, ctx)` — local rows for the user.
- `forgetInstallation(session, ctx)` — delete local rows keyed on
  `(github_installation_id, user_id)`; the user still uninstalls on
  github.com.

## Notes

- Used by `routers/github.py` (install URL, repo list, setup
  callback) and the webhook install handlers. DB sessions come from
  the caller.
