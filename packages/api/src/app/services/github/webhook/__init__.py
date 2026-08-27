"""Webhook sub-service: GitHub webhook event handling.

The single entry point is :func:`handleWebhookEvent`: it takes the
verified delivery pieces, dispatches through the ``(event, action)``
registry (:data:`app.services.github.webhook.service.webhookRegistry`),
and returns a :class:`WebhookResult` ack. The concrete handlers live in
:mod:`.handlers`; the registry and result types in :mod:`.types`.
"""

from app.services.github.webhook.handlers import (
    handleInstallationDeleted,
    handleInstallationReposAdded,
    handleInstallationReposRemoved,
    handleInstallationSuspended,
    handleInstallationUnsuspended,
    handleIssueCommentCreated,
    handlePullRequestOpened,
    handlePush,
)
from app.services.github.webhook.service import handleWebhookEvent
from app.services.github.webhook.types import (
    WebhookCtx,
    WebhookHandler,
    WebhookRegistry,
    WebhookResult,
)

__all__ = [
    "WebhookCtx",
    "WebhookHandler",
    "WebhookRegistry",
    "WebhookResult",
    "handleInstallationDeleted",
    "handleInstallationReposAdded",
    "handleInstallationReposRemoved",
    "handleInstallationSuspended",
    "handleInstallationUnsuspended",
    "handleIssueCommentCreated",
    "handlePullRequestOpened",
    "handlePush",
    "handleWebhookEvent",
]