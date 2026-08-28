"""Agent service.

Submodules:

- :mod:`.models`    — Pydantic response schemas the review agents emit
  (legacy leaf, kept as-is).
- :mod:`.prompts`   — system prompts (summarizer + comments agent)
  (legacy leaf, kept as-is).
- :mod:`.helpers`   — shared deepagents helpers (legacy leaf, kept
  as-is).
- :mod:`.types`     — the service contract: :class:`ReviewAgentCtx`
  (identity + injected live deps) and the :class:`DeepAgentGraph`
  alias.
- :mod:`.errors`    — typed error values (:class:`AgentBuildError`).
- :mod:`.middleware` — the shared middleware stack
  (:func:`buildAgentMiddleware`).
- :mod:`.tools`     — agent tools (:func:`makeGetDiffTool` +
  :func:`getReviewDiffDirPath`).
- :mod:`.service`   — the entry points (camelCase): ctx factory +
  per-lane agent builders + pure combine/verdict/prompt helpers.
"""

from app.services.agent.errors import AgentBuildError
from app.services.agent.middleware import buildAgentMiddleware
from app.services.agent.service import (
    combineReviewResults,
    createCommentsAgent,
    createReviewAgentCtx,
    createSummaryAgent,
    createUserPrompt,
    verdictFor,
)
from app.services.agent.tools import getReviewDiffDirPath, makeGetDiffTool
from app.services.agent.types import (
    AgentMiddlewareStack,
    DeepAgentGraph,
    ReviewAgentCtx,
)

__all__ = [
    "AgentBuildError",
    "AgentMiddlewareStack",
    "DeepAgentGraph",
    "ReviewAgentCtx",
    "createUserPrompt",
    "buildAgentMiddleware",
    "combineReviewResults",
    "createCommentsAgent",
    "createReviewAgentCtx",
    "createSummaryAgent",
    "getReviewDiffDirPath",
    "makeGetDiffTool",
    "verdictFor",
]
