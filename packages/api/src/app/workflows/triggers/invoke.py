"""Thin webhook adapters: pure extraction + one best-effort Invoke.

No DB, no GitHub fetch. All ctx resolution runs as checkpointed steps
inside the durable handlers. Every business skip returns ReviewTriggerAck;
invoke infra failures raise so GitHub redelivers.
"""

from __future__ import annotations

import logging

from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.workflows.durable.invoke import invokeCommentDurable, invokeOpenedDurable
from app.workflows.durable.naming import (
    createCommentExecutionName,
    createOpenedExecutionName,
)
from app.workflows.durable.types import CommentDurableEvent, OpenedDurableEvent
from app.workflows.triggers.comment_payload import classifyComment, validateCommentPayload
from app.workflows.triggers.opened_payload import extractOpenedPrPayload
from app.workflows.triggers.types import ReviewTriggerAck

log = logging.getLogger(__name__)


def _traceCtxForTrigger(
    *, delivery: str, executionName: str, trigger: str
) -> dict | None:
    """Mint the serializable TraceCtx join keys. Never raises."""
    try:
        import uuid

        from app.services.observability.service import createTraceCtx

        try:
            from app.core.telemetry import current_trace_id

            traceId = current_trace_id() or uuid.uuid4().hex
        except Exception:
            traceId = uuid.uuid4().hex
        if trigger not in ("opened", "comment", "repair"):
            trigger = "opened"
        result = createTraceCtx(
            traceId=traceId,  # type: ignore[arg-type]
            delivery=delivery,  # type: ignore[arg-type]
            executionName=executionName,  # type: ignore[arg-type]
            trigger=trigger,  # type: ignore[arg-type]
        )
        from app.services.observability.errors import ObsValidationError

        if isinstance(result, ObsValidationError):
            return None
        return result.model_dump(mode="json")
    except Exception:
        return None


async def handlePullRequestOpened(
    payload: dict,
    delivery: str,
    session: AsyncSession,
) -> ReviewTriggerAck:
    _ = session
    pr = extractOpenedPrPayload(payload)
    if pr is None:
        return ReviewTriggerAck(
            accepted=False,
            action="opened",
            delivery=delivery,
            skip_reason="malformed_payload",
        )
    executionName = createOpenedExecutionName(
        ghRepoId=pr.ghRepoId,
        prNumber=int(pr.number),
        headSha=str(pr.headSha),
    )
    traceCtxPayload = _traceCtxForTrigger(
        delivery=delivery,
        executionName=executionName,
        trigger="opened",
    )
    result = await invokeOpenedDurable(
        function_name=settings.review_opened_function_name,
        event=OpenedDurableEvent(
            delivery=delivery,
            execution_name=executionName,
            payload=payload,
            traceCtx=traceCtxPayload,
        ),
    )
    if not result.invoked:
        raise RuntimeError(f"opened durable invoke failed: {result.error}")
    log.info(
        "trigger.opened: invoked delivery=%s exec=%s pr=%s head=%s",
        delivery,
        executionName,
        pr.number,
        pr.headSha,
    )
    return ReviewTriggerAck(accepted=True, action="opened", delivery=delivery)


async def handleIssueCommentCreated(
    payload: dict,
    delivery: str,
    session: AsyncSession,
) -> ReviewTriggerAck:
    _ = session
    trigger = validateCommentPayload(payload, delivery=delivery)
    if trigger is None:
        return ReviewTriggerAck(
            accepted=False,
            action="issue_comment",
            delivery=delivery,
            skip_reason="malformed_payload",
        )
    classified = classifyComment(payload, appSlug=settings.github_app_slug)
    if not classified.shouldProceed:
        return ReviewTriggerAck(
            accepted=False,
            action="issue_comment",
            delivery=delivery,
            skip_reason=classified.skipReason or "not_created",
        )
    executionName = createCommentExecutionName(
        ghRepoId=trigger.ghRepoId,
        prNumber=int(trigger.prNumber),
        delivery=delivery,
    )
    traceCtxPayload = _traceCtxForTrigger(
        delivery=delivery,
        executionName=executionName,
        trigger="comment",
    )
    result = await invokeCommentDurable(
        function_name=settings.review_comment_function_name,
        event=CommentDurableEvent(
            delivery=delivery,
            execution_name=executionName,
            payload=payload,
            traceCtx=traceCtxPayload,
        ),
    )
    if not result.invoked:
        raise RuntimeError(f"comment durable invoke failed: {result.error}")
    log.info(
        "trigger.comment: invoked delivery=%s exec=%s pr=%s",
        delivery,
        executionName,
        trigger.prNumber,
    )
    return ReviewTriggerAck(accepted=True, action="issue_comment", delivery=delivery)


__all__ = ["handleIssueCommentCreated", "handlePullRequestOpened"]
