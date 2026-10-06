"""Best-effort async Invoke helpers (I/O at the edge).

Runs in ApiFunction only — never inside a durable handler. Uses boto3
lambda:Invoke with InvocationType=Event plus DurableExecutionName for
dedupe. Blocking boto calls run in a worker thread. Never raises for
business outcomes; infra failures return invoked=False so the trigger
raises and GitHub redelivers.
"""

from __future__ import annotations

import asyncio
import json
import logging

import boto3

from app.workflows.durable.types import (
    CommentDurableEvent,
    DurableInvokeResult,
    DurableRepairEvent,
    OpenedDurableEvent,
)

log = logging.getLogger(__name__)


def invokeEventSync(*, functionName: str, executionName: str, payload: dict) -> None:
    client = boto3.client("lambda")
    client.invoke(
        FunctionName=functionName,
        Qualifier="$LATEST",
        InvocationType="Event",
        Payload=json.dumps(payload).encode("utf-8"),
        DurableExecutionName=executionName,
    )


async def invokeEvent(
    *, functionName: str, executionName: str, payload: dict
) -> DurableInvokeResult:
    try:
        await asyncio.to_thread(
            invokeEventSync,
            functionName=functionName,
            executionName=executionName,
            payload={**payload, "_durableExecutionName": executionName},
        )
    except Exception as exc:
        log.warning(
            "durable.invoke: failed function=%s exec=%s: %s: %s",
            functionName,
            executionName,
            type(exc).__name__,
            exc,
        )
        return DurableInvokeResult(
            invoked=False,
            execution_name=executionName,
            function_name=functionName,
            error=f"{type(exc).__name__}: {exc}",
        )
    log.info("durable.invoke: ok function=%s exec=%s", functionName, executionName)
    return DurableInvokeResult(
        invoked=True,
        execution_name=executionName,
        function_name=functionName,
    )


async def invokeOpenedDurable(
    *, function_name: str, event: OpenedDurableEvent
) -> DurableInvokeResult:
    if not function_name:
        return DurableInvokeResult(
            invoked=False, error="opened durable function name not configured"
        )
    return await invokeEvent(
        functionName=function_name,
        executionName=event.execution_name,
        payload=event.model_dump(mode="json"),
    )


async def invokeCommentDurable(
    *, function_name: str, event: CommentDurableEvent
) -> DurableInvokeResult:
    if not function_name:
        return DurableInvokeResult(
            invoked=False, error="comment durable function name not configured"
        )
    return await invokeEvent(
        functionName=function_name,
        executionName=event.execution_name,
        payload=event.model_dump(mode="json"),
    )


async def invokeRepairDurable(
    *, function_name: str, event: DurableRepairEvent
) -> DurableInvokeResult:
    if not function_name:
        return DurableInvokeResult(
            invoked=False, error="repair durable function name not configured"
        )
    return await invokeEvent(
        functionName=function_name,
        executionName=event.execution_name,
        payload=event.model_dump(mode="json"),
    )


__all__ = ["invokeCommentDurable", "invokeOpenedDurable", "invokeRepairDurable"]
