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
- :mod:`.prompts`   — prompt constants (placeholders — wording lands
  in a dedicated prompt session) and the shared output markers.
- :mod:`.service`   — the entry points (camelCase): ctx factory +
  agent builders + pure user-prompt helpers.
"""

from app.services.agent_v2.errors import AgentV2BuildError
from app.services.agent_v2.prompts import (
    FILE_REVIEW_SYSTEM_PROMPT,
    NO_FINDINGS_MARKER,
    PLANNING_SYSTEM_PROMPT,
    PLAN_EXTRACTION_SYSTEM_PROMPT,
)
from app.services.agent_v2.service import (
    buildNoSubAgent,
    buildNoSubBackend,
    chunkFileForPath,
    createAgentV2Ctx,
    createFileReviewAgent,
    createFileReviewUserPrompt,
    createPlanningAgent,
    createPlanningUserPrompt,
)
from app.services.agent_v2.types import (
    AgentV2Ctx,
    ChunkInventory,
    DeepAgentGraph,
    FileContext,
    FileReviewJob,
    PlannerContext,
)

__all__ = [
    "AgentV2BuildError",
    "AgentV2Ctx",
    "ChunkInventory",
    "DeepAgentGraph",
    "FileContext",
    "FileReviewJob",
    "FILE_REVIEW_SYSTEM_PROMPT",
    "NO_FINDINGS_MARKER",
    "PLANNING_SYSTEM_PROMPT",
    "PLAN_EXTRACTION_SYSTEM_PROMPT",
    "PlannerContext",
    "buildNoSubAgent",
    "buildNoSubBackend",
    "chunkFileForPath",
    "createAgentV2Ctx",
    "createFileReviewAgent",
    "createFileReviewUserPrompt",
    "createPlanningAgent",
    "createPlanningUserPrompt",
]
