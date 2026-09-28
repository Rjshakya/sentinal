# github/webhook — delivery dispatch for GitHub events

Single entry point plus a `(event, action)` registry. Install
events are mirrored to the local DB here; PR/comment events
delegate to the workflow triggers.

## Layout

- `service.py` — `handleWebhookEvent(payload)` → registry lookup →
  handler. `webhookRegistry` holds the `(event, action)` table.
- `handlers.py` — concrete handlers: install lifecycle
  (`handleInstallationDeleted/Suspended/Unsuspended`,
  `handleInstallationReposAdded/Removed` write `installations` /
  `repos` rows), delegation (`handlePullRequestOpened`,
  `handleIssueCommentCreated` → triggers), `handlePush` (accepted,
  no indexing — pipeline removed).
- `types.py` — `WebhookCtx` (delivery payload), `WebhookResult`
  (accepted + skip reason), `WebhookHandler` protocol,
  `WebhookRegistry`.

## Notes

- Used only by `routers/webhooks.py`, which owns signature
  verification; this package never trusts the caller, only the
  payload shape.
- Handlers take the caller's `AsyncSession` for mirror writes;
  delegation handlers import trigger adapters lazily (cycle
  avoidance — workflows are registered via `main.py` imports).
