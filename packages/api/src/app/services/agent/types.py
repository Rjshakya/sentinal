"""Agent service types: ctx + result projections.

This module owns the *contract* of the agent service: the
:class:`ReviewAgentCtx` (identity + injected live dependencies) and
the :class:`DeepAgentGraph` alias for the compiled deepagents state
graph.

Naming convention: this package intentionally uses **camelCase**
identifiers — the same convention as :mod:`app.services.github`,
:mod:`app.services.llm`, and :mod:`app.services.sandbox`. Ids that are
also identifiers (id, ctx) keep their single-word lowercase form.

Design notes:

- :class:`ReviewAgentCtx` is a plain Pydantic model carrying identity
  plus injected live dependencies (the lane's chat model and the
  sandbox handle), assembled by the ctx factory
  (:func:`app.services.agent.service.createReviewAgentCtx`) at the
  edge. **Not serializable** — it carries a :class:`BaseChatModel` and
  an :class:`E2BSandbox`, so it never crosses a DBOS workflow
  boundary; callers build it per run inside their steps.
- Ids are **branded types** (``NewType`` over ``str`` / ``int`` from
  :mod:`app.utils.branded`): they erase at runtime (Pydantic
  validation is unaffected) but pyright enforces the branding
  statically, so a bare ``str`` cannot accidentally flow into a ctx.
- The sandbox type (:class:`app.core.sandbox.e2b.E2BSandbox`) is the
  legacy core handle for now; it swaps to the sandbox-service handle
  when the review pipeline consumes :mod:`app.services.sandbox`.
"""

from __future__ import annotations

from typing import Any, TypeAlias

from langchain.agents.middleware.types import AgentMiddleware
from langchain_core.language_models.chat_models import BaseChatModel
from langgraph.graph.state import CompiledStateGraph
from pydantic import BaseModel, ConfigDict, Field

from app.core.sandbox.e2b import E2BSandbox
from app.services.sandbox.types import SandboxCtx
from app.utils.branded import CommitId, PRNumber, RepoId, RepoName, UserId

DeepAgentGraph: TypeAlias = CompiledStateGraph[Any, Any, Any, Any]
"""The compiled langgraph state graph returned by ``create_deep_agent``.

The four ``Any`` type arguments mirror the graph's
``[StateT, ContextT, InputT, OutputT]`` parameterization; they are
explicit so the alias stays fully typed under strict checking and any
``CompiledStateGraph`` instance is assignable to it.

The alias is module-level so callers can name the return type of
:func:`app.services.agent.service.createSummaryAgent` and
:func:`app.services.agent.service.createCommentsAgent` without pulling
langgraph types into their own signatures."""

AgentMiddlewareStack: TypeAlias = list[AgentMiddleware[Any, None, Any]]
"""The middleware stack shape accepted by ``create_deep_agent``.

Each review agent runs through the shared stack built by
:func:`app.services.agent.middleware.buildAgentMiddleware`. The
``Any`` type parameters mirror :class:`langchain.agents.middleware.types.AgentMiddleware`'s
defaults — the built-in middleware instances use them."""

_DEFAULT_MODEL_CALL_RUN_LIMIT = 350
_DEFAULT_TOOL_CALL_RUN_LIMIT = 350


class ReviewAgentCtx(BaseModel):
    """Everything one review-agent build needs, as one object.

    The ctx is assembled by
    :func:`app.services.agent.service.createReviewAgentCtx` at the
    edge and consumed by :func:`createSummaryAgent` /
    :func:`createCommentsAgent`. It carries:

    - the run identity (user, repo, PR, head SHA) — branded,
    - the lane's chat model (injected — the agent service never
      builds models itself),
    - the sandbox handle the agent's tools read from,
    - the per-run model/tool call limits applied to the middleware
      stack.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    userId: UserId
    repoId: RepoId
    repoName: RepoName
    prNumber: PRNumber
    headSha: CommitId
    model: BaseChatModel
    """The lane's chat model. One instance per agent so each can carry
    its own per-agent callback handler."""
    sandboxCtx: SandboxCtx
    """The run's sandbox handle; the ``get_diff`` tool reads the PR
    diff artefacts from it."""
    modelCallRunLimit: int = Field(
        default=_DEFAULT_MODEL_CALL_RUN_LIMIT,
        ge=1,
        description="Ceiling on model calls per run (middleware cap).",
    )
    toolCallRunLimit: int = Field(
        default=_DEFAULT_TOOL_CALL_RUN_LIMIT,
        ge=1,
        description="Ceiling on tool executions per run (middleware cap).",
    )


__all__ = [
    "AgentMiddlewareStack",
    "DeepAgentGraph",
    "ReviewAgentCtx",
]
