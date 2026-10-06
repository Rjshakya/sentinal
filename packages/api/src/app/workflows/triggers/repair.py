"""Repair follow-up dispatch: review pipeline -> repair durable.

Called best-effort from the review pipeline when the inline post
returns ``posted=False``. Pure execution-name build + one Invoke;
infra failures raise so the caller logs and continues (never fail the
review over a repair dispatch).
"""

from __future__ import annotations

import logging

from app.core.config import settings
from app.workflows.durable.invoke import invokeRepairDurable
from app.workflows.durable.naming import createRepairExecutionName
from app.workflows.durable.types import DurableRepairEvent

log = logging.getLogger(__name__)


async def triggerRepairAfterReview(
    *,
    prNumber: int,
    commitId: str,
    delivery: str,
) -> bool:
    """Invoke the repair durable for an unposted review; True if invoked."""
    executionName = createRepairExecutionName(
        prNumber=prNumber,
        commitId=commitId,
    )
    result = await invokeRepairDurable(
        function_name=settings.repair_durable_function_name,
        event=DurableRepairEvent(
            delivery=delivery,
            pr_number=prNumber,
            commit_id=commitId,
            execution_name=executionName,
        ),
    )
    if not result.invoked:
        log.warning(
            "trigger.repair: invoke failed delivery=%s exec=%s: %s",
            delivery,
            executionName,
            result.error,
        )
        return False
    log.info(
        "trigger.repair: invoked delivery=%s exec=%s pr=%s commit=%s",
        delivery,
        executionName,
        prNumber,
        commitId[:7],
    )
    return True


__all__ = ["triggerRepairAfterReview"]
