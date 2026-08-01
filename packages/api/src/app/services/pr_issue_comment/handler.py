"""Router adapter: ``handle_issue_comment_created``.

The single public entry point called by
:func:`app.routers.webhooks.github_webhook` for every verified
``issue_comment`` delivery. The handler:

1. Computes the deterministic trigger workflow id
   ``trigger_issue_comment:{comment_id}``.
2. Wraps :func:`DBOS.start_workflow_async` in a
   :class:`SetWorkflowID` so redelivered GitHub webhooks for the
   same comment are deduped by DBOS.
3. Awaits the coroutine to enqueue the workflow, then returns the
   ``WebhookAck`` the router logs.

The handler never raises: a malformed payload (no
``payload["comment"]["id"]``) is folded into a
``skip_reason="malformed_payload"`` ack so the router can always
reply ``202 Accepted``. All other skip reasons live inside the
workflow's :class:`TriggerRunResult` and are surfaced through the
DBOS admin UI.
"""

from __future__ import annotations

import logging
from typing import Any

from dbos import DBOS, SetWorkflowID

from app.core.config import settings
from app.services.pr_issue_comment.workflow import trigger_issue_comment_workflow
from app.services.review.webhook import WebhookAck

log = logging.getLogger(__name__)


def _trigger_workflow_id(raw_payload: dict[str, Any]) -> str | None:
    """Return ``trigger_issue_comment:{comment_id}`` or ``None``.

    Returns ``None`` when the comment id is missing / not an int
    so the handler can return a ``malformed_payload`` ack without
    enqueueing a workflow.
    """
    comment = raw_payload.get("comment") or {}
    comment_id = comment.get("id")
    if not isinstance(comment_id, int):
        return None
    return f"trigger_issue_comment:{comment_id}"


def _delivery(raw_payload: dict[str, Any], provided: str) -> str:
    """Carry the delivery id through the trigger workflow.

    The comment payload does not embed the delivery id; it comes
    from the ``X-GitHub-Delivery`` header. The handler threads it
    in via the workflow input so the typed view carries it.
    """
    return provided or "unknown"


async def handle_issue_comment_created(
    raw_payload: dict[str, Any],
    delivery: str,
) -> WebhookAck:
    """Enqueue a ``trigger_issue_comment_workflow`` for one delivery.

    Args:
        raw_payload: The verified ``issue_comment`` JSON body. The
            caller has already validated the signature.
        delivery: The ``X-GitHub-Delivery`` header value. Carried
            into the workflow's typed view for logging.

    Returns:
        A :class:`WebhookAck`. ``accepted=True`` means the workflow
        was enqueued; the actual dispatch decision (review ran vs.
        skipped) lives in the DBOS workflow result, queryable via
        the DBOS admin UI.
    """
    trigger_id = _trigger_workflow_id(raw_payload)
    if trigger_id is None:
        log.warning(
            "pr_issue_comment.handle_issue_comment_created: missing comment id: "
            "delivery=%s",
            delivery,
        )
        return WebhookAck(
            accepted=False,
            action="issue_comment",
            delivery=delivery,
            skip_reason="malformed_payload",
        )

    app_slug = settings.github_app_slug or "reviewpr"
    effective_delivery = _delivery(raw_payload, delivery)

    log.info(
        "pr_issue_comment.handle_issue_comment_created: starting workflow: "
        "delivery=%s trigger_id=%s app_slug=%s",
        effective_delivery,
        trigger_id,
        app_slug,
    )

    with SetWorkflowID(trigger_id):
        await DBOS.start_workflow_async(
            trigger_issue_comment_workflow,
            raw_payload,
            effective_delivery,
            app_slug,
        )

    return WebhookAck(
        accepted=True,
        action="issue_comment",
        delivery=effective_delivery,
    )


__all__ = ["handle_issue_comment_created"]
