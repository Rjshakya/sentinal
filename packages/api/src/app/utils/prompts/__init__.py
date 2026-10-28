"""Pi prompt factory (``app.utils.prompts``).

Pure formatting only: no I/O, no LLM, no sandbox calls. Each module
owns one agent (plan / review / summary) and exposes two builders:

- ``create<System>SystemPrompt`` — static role + sandbox layout.
- ``create<Agent>SessionPrompt`` — run-specific paths + PR intent +
  exact output schema.

The factory computes every absolute path from branded IDs via
:mod:`app.utils.sandbox_fs`, so prompt paths can never drift from the
run layout. It never mentions pi flags, tools, sessions, or working
directory — :mod:`app.services.pi_harness` owns those.
"""

from app.utils.prompts.plan import createPlanSessionPrompt, createPlanSystemPrompt
from app.utils.prompts.review import (
    createReviewSessionPrompt,
    createReviewSystemPrompt,
)
from app.utils.prompts.summary import (
    createSummarySessionPrompt,
    createSummarySystemPrompt,
)

__all__ = [
    "createPlanSessionPrompt",
    "createPlanSystemPrompt",
    "createReviewSessionPrompt",
    "createReviewSystemPrompt",
    "createSummarySessionPrompt",
    "createSummarySystemPrompt",
]
