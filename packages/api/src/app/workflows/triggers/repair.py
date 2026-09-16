"""Trigger adapter for the repair-and-publish workflow.

Owns the per-workflow dispatch of
:func:`app.workflows.repair_and_publish.workflow.repairAndPublishReviewWorkflow`
so the review comment trigger (and any future caller) dispatches repairs
through one place instead of reaching into the repair workflow directly.

The dispatch mechanics (deterministic workflow id + ``DBOS.start_workflow_async``)
stay in :mod:`app.workflows.repair_and_publish.workflow` — this module is
the trigger edge: it takes the already-resolved run environment
(:class:`LLMCtx` + :class:`SandboxCtx`) and fires the workflow.
"""

from __future__ import annotations

from app.services.llm.types import LLMCtx
from app.services.sandbox.types import SandboxCtx
from app.utils.branded import CommitId, PRNumber
from app.workflows.repair_and_publish.workflow import (
    DispatchRepairAndPublishWorkflowInput,
    dispatchRepairAndPublishWorkflow,
)


async def triggerRepairAfterReview(
    *,
    llmCtx: LLMCtx,
    sandboxCtx: SandboxCtx,
    prNumber: PRNumber,
    headSha: CommitId,
) -> str:
    """Dispatch the repair-and-publish workflow for a reviewed head.

    Returns the deterministic repair workflow id. Never raises for
    business outcomes; infrastructure failures propagate so the caller
    (and ultimately GitHub redelivery) observes them.
    """
    return await dispatchRepairAndPublishWorkflow(
        input=DispatchRepairAndPublishWorkflowInput(
            prNumber=prNumber,
            commitId=headSha,
            llmCtx=llmCtx,
            sandboxCtx=sandboxCtx,
        )
    )


__all__ = [
    "triggerRepairAfterReview",
]
