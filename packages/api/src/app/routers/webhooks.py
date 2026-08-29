"""GitHub App webhook receiver.

Verifies the ``X-Hub-Signature-256`` HMAC against
``settings.github_webhook_secret`` and hands the verified delivery to
the github webhook sub-service
(:func:`app.services.github.webhook.handleWebhookEvent`), which
dispatches the ``(event, action)`` pair through its registry:

- ``installation`` / ``installation_repositories`` -> local-DB mirror
  handlers (install-flow bookkeeping the setup callback does not
  cover).
- ``pull_request`` (``opened``) -> dispatches the review workflow
  (:func:`app.workflows.review.workflow.reviewWorkflow`).
- ``issue_comment`` (``created``) -> dispatches the review workflow
  (incremental re-review when the head moved since the last run).
- ``push`` -> dispatches the incremental indexing workflow (legacy
  adapter).
- anything else -> an ``accepted=False`` ack with
  ``skip_reason="unhandled_event"``.

The handler sits outside AuthMiddleware's protected prefixes: GitHub
calls this endpoint, not a logged-in user.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import Response

from app.core.config import settings
from app.core.db import async_session_maker
from app.services.github.webhook import handleWebhookEvent

router = APIRouter(prefix="/webhooks", tags=["webhooks"])
log = logging.getLogger(__name__)

GITHUB_SIGNATURE_HEADER = "X-Hub-Signature-256"
GITHUB_EVENT_HEADER = "X-GitHub-Event"
GITHUB_DELIVERY_HEADER = "X-GitHub-Delivery"
SIGNATURE_PREFIX = "sha256="

_EVENTS_WITH_ACTION = frozenset(
    {"installation", "installation_repositories", "pull_request", "issue_comment"}
)
"""Events whose payloads carry an ``action`` field; ``push`` does not."""


def _verify_signature(secret: str, body: bytes, signature_header: str | None) -> bool:
    """Constant-time HMAC-SHA256 check.

    Returns ``False`` for any malformed input (missing header, wrong
    scheme, mismatched digest) - never raises. The caller is expected
    to treat the body as untrusted on a ``False`` result.
    """
    if not signature_header or not signature_header.startswith(SIGNATURE_PREFIX):
        return False
    provided = signature_header[len(SIGNATURE_PREFIX) :]
    expected = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(provided, expected)


def _action_for(event: str, payload: dict[str, Any]) -> str | None:
    """Return the payload's ``action`` for actioned events, else ``None``.

    ``push`` deliveries carry no ``action``; the registry keys them as
    ``("push", None)``.
    """
    if event not in _EVENTS_WITH_ACTION:
        return None
    action = payload.get("action")
    return action if isinstance(action, str) else None


@router.post("/github")
async def github_webhook(
    request: Request,
) -> Response:
    body = await request.body()

    if not _verify_signature(
        settings.github_webhook_secret,
        body,
        request.headers.get(GITHUB_SIGNATURE_HEADER),
    ):
        log.warning(
            "github_webhook: rejected (bad signature, %d bytes)",
            len(body),
        )
        return Response(status_code=401)

    event = request.headers.get(GITHUB_EVENT_HEADER) or "unknown"
    delivery = request.headers.get(GITHUB_DELIVERY_HEADER) or "unknown"

    if event == "ping":
        log.info("github_webhook: ping accepted (delivery=%s)", delivery)
        return Response(status_code=200)

    try:
        payload = json.loads(body) if body else {}
    except json.JSONDecodeError:
        log.warning(
            "github_webhook: invalid JSON (delivery=%s, bytes=%d)",
            delivery,
            len(body),
        )
        return Response(status_code=202)

    async with async_session_maker() as session:
        result = await handleWebhookEvent(
            session=session,
            event=event,
            action=_action_for(event, payload),
            delivery=delivery,
            payload=payload,
        )

    log.info(
        "github_webhook: handled event=%s action=%s delivery=%s accepted=%s "
        "skip_reason=%s",
        result.event,
        result.action,
        result.delivery,
        result.accepted,
        result.skipReason,
    )
    return Response(status_code=202)
