"""System prompts for the v2 agents (planning + per-file review).

Placeholders on purpose: the current prompts are not good enough, so
prompt wording gets a dedicated session later. This module reserves
the prompt surface — one constant per agent plus the shared output
markers — so the architecture (builders, steps, workflow) can land
without churning once the real prompts are written.

- ``PLANNING_SYSTEM_PROMPT`` → the planning agent (repo exploration +
  per-file enrichment). Decided shape: structured
  :class:`PlannerContext` output (see the plan-extraction prompt).
- ``FILE_REVIEW_SYSTEM_PROMPT`` → one per-file review agent (single
  chunk, findings report or ``NO_FINDINGS``).
- ``PLAN_EXTRACTION_SYSTEM_PROMPT`` → the structured-output extractor
  that validates the planner's free text into
  :class:`PlannerContext` (mirrors the comments-extractor pattern in
  the v1 pipeline).
"""

from __future__ import annotations

PLANNING_SYSTEM_PROMPT: str = " "
"""System prompt for the planning agent.

TODO(prompt-session): repo-exploration rubric — map manifests, major
directories, entrypoints, public surfaces; trace representative
end-to-end control/data flows (callers, state/persistence, failure
handling, configuration, operations, integrations); inspect focused
tests and neighboring implementations; stop when the major systems
are evidence-backed (no exhaustive inventory). Output per-file
enrichment (focus lenses, cross-file callers/callees, relevant
symbols) plus repo-level context.
"""

FILE_REVIEW_SYSTEM_PROMPT: str = " "
"""System prompt for one per-file review agent.

TODO(prompt-session): single-chunk rubric — correctness / strict bugs
(input → path → wrong outcome, no hypotheticals) / blast radius
(verify with grep) / performance with evidence / security / broken
patterns; gutter-visible anchors only; findings-report blocks shaped
like the v1 comments agent; ``NO_FINDINGS`` when clean.
"""

PLAN_EXTRACTION_SYSTEM_PROMPT: str = " "
"""System prompt for the plan extractor (free text → PlannerContext).

TODO(prompt-session): strict transcription — copy file paths,
symbols, and context strings verbatim; never invent files; drop
entries without a usable file path; empty/default PlannerContext on
``NO_PLAN``.
"""

NO_FINDINGS_MARKER: str = "NO_FINDINGS"
"""Exact marker a file agent emits when its chunk is clean.

The combine step treats it as a successful empty outcome (no
extractor call for that file's text beyond the shared merge).
"""

__all__ = [
    "FILE_REVIEW_SYSTEM_PROMPT",
    "NO_FINDINGS_MARKER",
    "PLANNING_SYSTEM_PROMPT",
    "PLAN_EXTRACTION_SYSTEM_PROMPT",
]
