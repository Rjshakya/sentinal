"""Durable entry point for repair-and-publish (linear, guard-clauses).

Validates the event once, then runs the shared repair phase. This
handler only serves repair.
"""

from __future__ import annotations

from aws_durable_execution_sdk_python import durable_execution
from aws_durable_execution_sdk_python.context import DurableContext

from app.workflows.durable.repair_pipeline import RepairPhaseInput, runRepairPhase
from app.workflows.durable.types import DurableRepairEvent


@durable_execution
def repair_durable_handler(event: dict, ctx: DurableContext) -> dict:
    request = DurableRepairEvent.model_validate(event)
    return runRepairPhase(
        ctx,
        input=RepairPhaseInput(
            delivery=request.delivery,
            executionName=request.execution_name,
            commitId=request.commit_id,
        ),
    )


__all__ = ["repair_durable_handler"]
