"""Agent-v2 service: planning agent + per-file review agents.

The isolated successor of :mod:`app.services.agent` for the v2 review
flow: one planning agent (repo exploration + per-file enrichment)
followed by one deep-agent per changed file. Every agent is built
with delegation disabled (``subagents=[]`` plus the
no-delegation middleware guard) — no subagents anywhere.

Submodules:

- :mod:`.types`     — the service contract: :class:`AgentV2Ctx`
  (identity + injected live deps), the serializable planner payloads
  (:class:`PlannerContext` / :class:`FileContext`), and the
  host-side join inputs (:class:`ChunkInventory` /
  :class:`FileReviewJob`).
- :mod:`.errors`    — typed error values (:class:`AgentV2BuildError`).
- :mod:`.prompts`   — one function per prompt: system builders take
  narrow scalars (identity + tool budget), user builders take the
  ctx plus run data (inventory / job / PR intent). Plus the shared
  blocks (comment-body contract, output markers).
- :mod:`.service`   — the entry points (camelCase): ctx factory +
  agent builders. Owns no prompt wording (imports from
  :mod:`.prompts`) and no middleware assembly (imports from
  :mod:`._middleware`).
"""

from app.services.agent_v2.errors import AgentV2BuildError
from app.services.agent_v2.prompts import (
    COMMENT_BODY_FORMAT,
    NO_FINDINGS_MARKER,
    SUBMIT_PLAN_TOOL_DESCRIPTION,
    createFileReviewSystemPrompt,
    createFileReviewUserPrompt,
    createPlanningSystemPrompt,
    createPlanningUserPrompt,
    identityHeader,
    prMetaBlock,
)
from app.services.agent_v2.service import (
    buildNoSubAgent,
    buildNoSubBackend,
    buildSubmitPlanTool,
    createAgentV2Ctx,
    createFileReviewAgent,
    createPlanningAgent,
    planFilePath,
)
from app.services.agent_v2.types import (
    AgentV2Ctx,
    ChunkInventory,
    ChunkRef,
    DeepAgentGraph,
    FileContext,
    FileReviewJob,
    PlannerContext,
)

__all__ = [
    "AgentV2BuildError",
    "AgentV2Ctx",
    "COMMENT_BODY_FORMAT",
    "ChunkInventory",
    "ChunkRef",
    "DeepAgentGraph",
    "FileContext",
    "FileReviewJob",
    "NO_FINDINGS_MARKER",
    "PlannerContext",
    "SUBMIT_PLAN_TOOL_DESCRIPTION",
    "buildNoSubAgent",
    "buildNoSubBackend",
    "buildSubmitPlanTool",
    "createAgentV2Ctx",
    "createFileReviewAgent",
    "createFileReviewSystemPrompt",
    "createFileReviewUserPrompt",
    "createPlanningAgent",
    "createPlanningSystemPrompt",
    "createPlanningUserPrompt",
    "identityHeader",
    "planFilePath",
    "prMetaBlock",
]
