"""Built-in agent middleware for the review deep agents.

The two review agents (:func:`app.services.review.agent.build_summary_agent`
and :func:`app.services.review.agent.build_comments_agent`) run through a
shared middleware stack built by :func:`build_review_middleware`:

- :class:`ModelRetryMiddleware` — retries model-call failures with
  exponential backoff (max 3 retries, 1s initial delay, 2x factor).
  ``on_failure="error"`` re-raises the original exception after the
  retries are exhausted, so the existing per-lane error classification
  (:func:`app.services.review.errors.is_llm_retry_error` → DBOS step
  retry → Sentry capture) keeps working unchanged.
- :class:`ModelCallLimitMiddleware` — caps model calls per run (50) so
  a confused agent cannot burn the LLM budget in a tight loop.
- :class:`ToolCallLimitMiddleware` — caps tool executions per run (200)
  as the same runaway protection for tool calls.

Only built-in middleware is used; the stock async variants
(``awrap_model_call`` / ``awrap_tool_call``) are selected automatically
on ``ainvoke``, so the backoff sleeps are ``asyncio.sleep`` and never
block the event loop.

This module is pure: no I/O, no session, no clock. The middleware list
is shared, stateless between runs, and safe to construct once per
agent build.
"""

from __future__ import annotations

from typing import Any

from langchain.agents.middleware import (
    AgentMiddleware,
    ModelCallLimitMiddleware,
    ModelRetryMiddleware,
    ToolCallLimitMiddleware,
)

_MODEL_MAX_RETRIES = 3
_MODEL_BACKOFF_FACTOR = 2.0
_MODEL_INITIAL_DELAY = 1.0

_MODEL_CALL_RUN_LIMIT = 50
_TOOL_CALL_RUN_LIMIT = 200


def build_review_middleware() -> list[AgentMiddleware[Any, None, Any]]:
    """Build the shared middleware stack for both review agents.

    Order matters: the first entry is the outermost layer, so the
    model retry wraps the underlying model call and the call-limit
    middlewares sit outside it as graph-node hooks.

    Returns:
        A fresh list of middleware instances. The instances are
        stateless and safe to reuse across agent builds; a new list is
        returned anyway so callers never share mutable middleware state.
    """
    return [
        ModelRetryMiddleware(
            max_retries=_MODEL_MAX_RETRIES,
            backoff_factor=_MODEL_BACKOFF_FACTOR,
            initial_delay=_MODEL_INITIAL_DELAY,
            on_failure="error",
        ),
        ModelCallLimitMiddleware(run_limit=_MODEL_CALL_RUN_LIMIT),
        ToolCallLimitMiddleware(run_limit=_TOOL_CALL_RUN_LIMIT),
    ]


__all__: list[str] = ["build_review_middleware"]
