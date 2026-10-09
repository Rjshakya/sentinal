"""Durable entry point for repair-and-publish (linear, guard-clauses).

Validates the event once, then runs the shared repair phase. This
handler only serves repair.
"""

from __future__ import annotations

from aws_durable_execution_sdk_python import durable_execution
from aws_durable_execution_sdk_python.context import DurableContext

from app.workflows.durable.repair_pipeline import RepairPhaseInput, runRepairPhase
from app.workflows.durable.types import DurableRepairEvent
from app.core.telemetry import (
    extract_trace_context,
    force_flush_telemetry,
    init_telemetry,
    start_span,
)

init_telemetry()


@durable_execution
def repair_durable_handler(event: dict, ctx: DurableContext) -> dict:
    request = DurableRepairEvent.model_validate(event)
    parent = extract_trace_context(
        {
            "traceparent": request.traceparent or "",
            "tracestate": request.tracestate or "",
        }
    )
    token = None
    if parent is not None:
        try:
            from opentelemetry import context as otel_context

            token = otel_context.attach(parent)
        except Exception:
            token = None
    import time as _time

    _started = _time.perf_counter()
    try:
        with start_span(
            "repairDurableHandler",
            attributes={
                "sentinel.delivery": request.delivery,
                "sentinel.execution_name": request.execution_name,
                "sentinel.trigger": "repair",
            },
        ):
            return runRepairPhase(
                ctx,
                input=RepairPhaseInput(
                    delivery=request.delivery,
                    executionName=request.execution_name,
                    commitId=request.commit_id,
                ),
            )
    finally:
        try:
            from app.core.telemetry import get_histogram

            get_histogram(
                "sentinel.handler_duration", description="Durable handler duration"
            ).record(
                _time.perf_counter() - _started, attributes={"trigger": "repair"}
            )
        except Exception:
            pass
        if token is not None:
            try:
                from opentelemetry import context as otel_context

                otel_context.detach(token)
            except Exception:
                pass
        try:
            force_flush_telemetry(1000)
        except Exception:
            pass


__all__ = ["repair_durable_handler"]
