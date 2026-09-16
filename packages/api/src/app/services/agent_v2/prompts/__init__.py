"""Prompts for the v2 agents (planning + per-file review).

A package, not a module: every prompt is a **function** taking narrow
inputs it interpolates into the prompt string — never a bare constant
(except the extractor prompt, whose wording still lands in a dedicated
prompt session).

- :mod:`.shared`    — shared blocks: the v2-owned comment-body
  contract, output markers, identity/PR-intent builders, and the
  untouched plan-extraction prompt.
- :mod:`.planning`  — planning-agent system + user builders.
- :mod:`.file_review` — per-file-agent system + user builders.

Data flows one way: ``shared`` ← ``planning`` / ``file_review`` ←
:mod:`app.services.agent_v2.service` (agent builders) and the v2
workflow steps (user prompts). The steps never import lane modules
directly — only this package root.
"""

from app.services.agent_v2.prompts.file_review import (
    createFileReviewSystemPrompt,
    createFileReviewUserPrompt,
)
from app.services.agent_v2.prompts.planning import (
    SUBMIT_PLAN_TOOL_DESCRIPTION,
    createPlanningSystemPrompt,
    createPlanningUserPrompt,
)
from app.services.agent_v2.prompts.shared import (
    COMMENT_BODY_FORMAT,
    NO_FINDINGS_MARKER,
    identityHeader,
    prMetaBlock,
)

__all__ = [
    "COMMENT_BODY_FORMAT",
    "NO_FINDINGS_MARKER",
    "SUBMIT_PLAN_TOOL_DESCRIPTION",
    "createFileReviewSystemPrompt",
    "createFileReviewUserPrompt",
    "createPlanningSystemPrompt",
    "createPlanningUserPrompt",
    "identityHeader",
    "prMetaBlock",
]
