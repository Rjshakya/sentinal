"""Durable entry point for repair-and-publish (linear, guard-clauses).

Validates the event once, then runs the shared repair phase. This
handler only serves repair.
"""

from __future__ import annotations

from async_durable_execution import durable_execution

from app.services.tracing.service import flushTraces
from app.workflows.durable.repair_pipeline import RepairPhaseInput, runRepairPhase
from app.workflows.durable.types import DurableRepairEvent


@durable_execution
async def repair_durable_handler(event: dict) -> dict:
    request = DurableRepairEvent.model_validate(event)
    try:
        return await runRepairPhase(
            input=RepairPhaseInput(
                delivery=request.delivery,
                executionName=request.execution_name,
                commitId=request.commit_id,
            ),
        )
    finally:
        flushTraces()


__all__ = ["repair_durable_handler"]
