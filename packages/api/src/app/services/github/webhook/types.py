"""Webhook sub-service types: ctx, result, handler protocol, registry.

This module owns the contract of the webhook sub-service: the
:class:`WebhookCtx` (the verified delivery envelope handed to event
handlers), the unified :class:`WebhookResult` ack, the
:class:`WebhookHandler` callable protocol, and the
:class:`WebhookRegistry` keyed by ``(event, action)``.

Naming convention: this package intentionally uses **camelCase**
identifiers — the same convention as :mod:`app.services.llm` and
:mod:`app.services.sandbox`.
"""

from __future__ import annotations

from typing import Any, Protocol

from pydantic import BaseModel
from sqlmodel.ext.asyncio.session import AsyncSession


class WebhookCtx(BaseModel):
    """One verified GitHub webhook delivery, handed to its handler."""

    event: str
    action: str | None = None
    delivery: str
    payload: dict[str, Any]
    accepted: bool
    skipReason: str | None = None


class WebhookResult(BaseModel):
    """Unified ack returned by :func:`handleWebhookEvent` for every delivery.

    ``accepted`` means the event was handled (workflow enqueued or DB
    mirror updated); a ``skipReason`` explains why it was not.
    """

    accepted: bool
    event: str
    action: str | None = None
    delivery: str
    skipReason: str | None = None


class WebhookHandler(Protocol):
    """A callable that handles one ``(event, action)`` delivery."""

    async def __call__(self, ctx: WebhookCtx, session: AsyncSession) -> None: ...


class WebhookRegistry:
    """Registry mapping ``(event, action)`` to its handler."""

    def __init__(self) -> None:
        self._handlers: dict[tuple[str, str | None], WebhookHandler] = {}

    def register(self, event: str, action: str | None, handler: WebhookHandler) -> None:
        self._handlers[(event, action)] = handler

    def get(self, event: str, action: str | None) -> WebhookHandler | None:
        return self._handlers.get((event, action))


__all__ = ["WebhookCtx", "WebhookHandler", "WebhookRegistry", "WebhookResult"]
