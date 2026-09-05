"""Webhook sub-service: one entry point, registry dispatch.

:func:`handleWebhookEvent` is the single entry point. It takes the raw
delivery pieces (event, action, delivery id, payload) plus the caller's
:class:`AsyncSession`, builds a :class:`WebhookCtx`, looks the
``(event, action)`` pair up in the module-level :data:`webhookRegistry`,
and hands the ctx to the matching handler.

Every outcome — handled, skipped, or unknown — is returned as a
:class:`WebhookResult` (the ack); the function never raises.
"""

from __future__ import annotations

from typing import Any

from sqlmodel.ext.asyncio.session import AsyncSession

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
from app.services.github.webhook.types import WebhookCtx, WebhookRegistry, WebhookResult

webhookRegistry = WebhookRegistry()

webhookRegistry.register("installation", "deleted", handleInstallationDeleted)
webhookRegistry.register("installation", "suspend", handleInstallationSuspended)
webhookRegistry.register("installation", "unsuspend", handleInstallationUnsuspended)
webhookRegistry.register(
    "installation_repositories", "added", handleInstallationReposAdded
)
webhookRegistry.register(
    "installation_repositories", "removed", handleInstallationReposRemoved
)
webhookRegistry.register("pull_request", "opened", handlePullRequestOpened)
webhookRegistry.register("issue_comment", "created", handleIssueCommentCreated)
webhookRegistry.register("push", None, handlePush)


def createWebHookResult(ctx: WebhookCtx, accepted: bool, skipReason: str | None = None):
    """Build the ack for ``ctx``, mirroring its event/action/delivery."""
    return WebhookResult(
        accepted=accepted,
        event=ctx.event,
        action=ctx.action,
        delivery=ctx.delivery,
        skipReason=skipReason,
    )


async def handleWebhookEvent(
    session: AsyncSession,
    event: str,
    action: str | None,
    delivery: str,
    payload: dict[str, Any],
) -> WebhookResult:
    """Handle one verified webhook delivery and return its ack.

    Args:
        session: The caller's :class:`AsyncSession` (handed to the
            mirror handlers; delegation handlers ignore it).
        event: The ``X-GitHub-Event`` header value.
        action: The payload's ``action`` field, or ``None`` for
            events without one (e.g. ``push``).
        delivery: The ``X-GitHub-Delivery`` header value.
        payload: The verified JSON body. The caller has already
            validated the signature.

    Returns:
        A :class:`WebhookResult`. ``accepted=False`` with
        ``skipReason="unhandled_event"`` means the ``(event, action)``
        pair has no registered handler.
    """
    ctx = WebhookCtx(
        event=event,
        action=action,
        delivery=delivery,
        payload=payload,
        accepted=False,
    )
    handler = webhookRegistry.get(event, action)
    if handler is None:
        return WebhookResult(
            accepted=False,
            event=event,
            action=action,
            delivery=delivery,
            skipReason="unhandled_event",
        )
    await handler(ctx, session)
    return createWebHookResult(ctx, ctx.accepted, ctx.skipReason)


__all__ = ["handleWebhookEvent", "webhookRegistry"]
