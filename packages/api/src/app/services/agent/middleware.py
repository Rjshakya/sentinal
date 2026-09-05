"""Built-in agent middleware for the review deep agents.

The two review agents
(:func:`app.services.agent.service.createSummaryAgent` and
:func:`app.services.agent.service.createCommentsAgent`) run through a
shared middleware stack built by :func:`buildAgentMiddleware`:

- :class:`ModelRetryMiddleware` — retries model-call failures with
  exponential backoff (max 3 retries, 1s initial delay, 2x factor).
  ``on_failure="error"`` re-raises the original exception after the
  retries are exhausted, so the existing per-lane error classification
  at the caller keeps working unchanged.
- :class:`ModelCallLimitMiddleware` — caps model calls per run so a
  confused agent cannot burn the LLM budget in a tight loop.
- :class:`ToolCallLimitMiddleware` — caps tool executions per run as
  the same runaway protection for tool calls.

Only built-in middleware is used; the stock async variants
(``awrap_model_call`` / ``awrap_tool_call``) are selected automatically
on ``ainvoke``, so the backoff sleeps are ``asyncio.sleep`` and never
block the event loop.

This module is pure: no I/O, no session, no clock. The middleware list
is shared, stateless between runs, and safe to construct once per
agent build.
"""

from __future__ import annotations

from langchain.agents.middleware import (
    ModelCallLimitMiddleware,
    ModelRetryMiddleware,
    ToolCallLimitMiddleware,
)

from app.services.agent.types import AgentMiddlewareStack

_MODEL_MAX_RETRIES = 3
_MODEL_BACKOFF_FACTOR = 2.0
_MODEL_INITIAL_DELAY = 1.0

_MODEL_CALL_RUN_LIMIT = 350
_TOOL_CALL_RUN_LIMIT = 350


def buildAgentMiddleware(
    *,
    modelCallRunLimit: int = _MODEL_CALL_RUN_LIMIT,
    toolCallRunLimit: int = _TOOL_CALL_RUN_LIMIT,
) -> AgentMiddlewareStack:
    """Build the shared middleware stack for both review agents.

    Order matters: the first entry is the outermost layer, so the
    model retry wraps the underlying model call and the call-limit
    middlewares sit outside it as graph-node hooks.

    The run limits default to the module constants
    (:data:`_MODEL_CALL_RUN_LIMIT` / :data:`_TOOL_CALL_RUN_LIMIT`);
    callers override them per run (e.g. from the PR's size).

    Returns:
        A fresh list of middleware instances. The instances are
        stateless and safe to reuse across agent builds; a new list is
        returned anyway so callers never share mutable middleware
        state.
    """
    return [
        ModelRetryMiddleware(
            max_retries=_MODEL_MAX_RETRIES,
            backoff_factor=_MODEL_BACKOFF_FACTOR,
            initial_delay=_MODEL_INITIAL_DELAY,
            on_failure="error",
        ),
        ModelCallLimitMiddleware(run_limit=modelCallRunLimit),
        ToolCallLimitMiddleware(run_limit=toolCallRunLimit),
    ]


__all__ = ["buildAgentMiddleware"]