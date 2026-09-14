"""No-subagent middleware for the v2 agents.

Module-private (leading underscore): only
:mod:`app.services.agent_v2.service` builds the v2 middleware stack.

Background: ``create_deep_agent`` auto-adds a default
``general-purpose`` subagent unless the harness profile disables it,
and profile registration is process-global — it would leak into the
v1 pipeline sharing the process. The per-agent, isolation-safe lever
is :class:`NoDelegationMiddleware`: it strips the ``task`` tool from
every model request, so the model can never delegate even though the
graph still carries the default subagent spec. ``subagents=[]`` is
passed alongside as intent documentation.

:class:`NoDelegationMiddleware` implements both the sync and async
model-call hooks (the v2 steps always ``ainvoke``, so the async hook
is the live one; the sync hook keeps ``invoke``/``stream`` safe).
It filters by tool *name* only and preserves every other tool object
verbatim, so backend built-ins (``read_file`` / ``ls`` / ``grep`` /
``glob`` / ``execute``) are unaffected regardless of their runtime
type.

:func:`buildNoSubMiddleware` is the shared stack: stock retry +
model/tool call caps (same policy as the v1 lanes) with the
no-delegation guard innermost (last = closest to the model call, so
it sees the final tool list).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from langchain.agents.middleware import (
    ModelCallLimitMiddleware,
    ModelRetryMiddleware,
    ToolCallLimitMiddleware,
)
from langchain.agents.middleware.types import (
    AgentMiddleware,
    ExtendedModelResponse,
    ModelRequest,
    ModelResponse,
)
from langchain_core.messages import AIMessage

_MODEL_MAX_RETRIES = 3
_MODEL_BACKOFF_FACTOR = 2.0
_MODEL_INITIAL_DELAY = 1.0


def _withoutTaskTool(request: ModelRequest[None]) -> ModelRequest[None]:
    """Return ``request`` with the ``task`` (delegation) tool removed."""
    return request.override(
        tools=[t for t in request.tools if getattr(t, "name", None) != "task"],
    )


class NoDelegationMiddleware(AgentMiddleware[Any, None, Any]):
    """Strip the ``task`` tool from every model request.

    Stateless: a single instance is safe to share across agent builds,
    but the builder constructs a fresh one per agent anyway so callers
    never share mutable middleware state.
    """

    def wrap_model_call(
        self,
        request: ModelRequest[None],
        handler: Callable[[ModelRequest[None]], ModelResponse[Any]],
    ) -> ModelResponse[Any] | AIMessage | ExtendedModelResponse[Any]:
        return handler(_withoutTaskTool(request))

    async def awrap_model_call(
        self,
        request: ModelRequest[None],
        handler: Callable[
            [ModelRequest[None]], Awaitable[ModelResponse[Any]]
        ],
    ) -> ModelResponse[Any] | AIMessage | ExtendedModelResponse[Any]:
        return await handler(_withoutTaskTool(request))


def buildNoSubMiddleware(
    *,
    modelCallRunLimit: int,
    toolCallRunLimit: int,
) -> list[AgentMiddleware[Any, None, Any]]:
    """Build the shared v2 middleware stack (no delegation).

    Order matters: the first entry is the outermost layer, so the
    model retry wraps the call, the call-limit guards sit outside it,
    and the no-delegation guard runs innermost on the final tool list.
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
        NoDelegationMiddleware(),
    ]


__all__ = ["NoDelegationMiddleware", "buildNoSubMiddleware"]
