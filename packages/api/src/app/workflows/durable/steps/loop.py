"""Sync bridge for durable steps: one fresh event loop per call.

Every ``@durable_step`` is sync, while every worker underneath is async.
This module owns the single bridge between the two: :func:`runStep`.

Why one helper instead of bare ``asyncio.run`` in each file:

- One choke point for loop hygiene. Each call builds a fresh loop via
  :func:`asyncio.new_event_loop`, sets it, drains it, closes it, and
  resets the current loop to ``None`` — so a later step can never pick
  up a closed loop handle via ``get_event_loop()``.
- Mirrors :func:`asyncio.run` cleanup (cancel pending tasks, shut down
  asyncgens and the default executor) without letting each step file
  drift into its own variant.
- Fails fast when called from a running loop instead of deadlocking or
  raising a confusing ``Event loop is closed`` far from the cause.

Strict types: the helper is generic over ``T`` and never returns
``Any``. Coroutine internals are typed as ``Any`` because workers span
DB, sandbox, and LLM boundaries.
"""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from typing import Any, TypeVar

T = TypeVar("T")


def _cancelAllTasks(loop: asyncio.AbstractEventLoop) -> None:
    """Cancel every pending task on ``loop`` (mirrors ``asyncio.run``)."""
    to_cancel = [task for task in asyncio.all_tasks(loop) if not task.done()]
    if not to_cancel:
        return
    for task in to_cancel:
        task.cancel()
    loop.run_until_complete(asyncio.gather(*to_cancel, return_exceptions=True))
    for task in to_cancel:
        if task.cancelled():
            continue
        exc = task.exception()
        if exc is not None:
            loop.call_exception_handler(
                {
                    "message": "unhandled exception during runStep shutdown",
                    "exception": exc,
                    "task": task,
                }
            )


def runStep(coro: Coroutine[Any, Any, T]) -> T:
    """Run ``coro`` to completion on a fresh, fully-closed event loop.

    Args:
        coro: The worker coroutine to drive (already constructed by the
            caller — validation happens before this call).

    Returns:
        Whatever ``coro`` returns, preserving its type ``T``.

    Raises:
        RuntimeError: Called from inside a running event loop. Durable
            steps are sync by contract, so this signals a programming
            error at the call site.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        pass
    else:
        coro.close()
        raise RuntimeError("runStep() cannot be called from a running event loop")

    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        return loop.run_until_complete(coro)
    finally:
        try:
            _cancelAllTasks(loop)
            loop.run_until_complete(loop.shutdown_asyncgens())
            loop.run_until_complete(loop.shutdown_default_executor())
        finally:
            asyncio.set_event_loop(None)
            loop.close()


__all__ = ["runStep"]
