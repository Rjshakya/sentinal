"""DBOS workflow triggers: webhook deliveries → workflow dispatches.

One module per workflow we trigger (the edge adapters that resolve the
run environment and dispatch under a deterministic workflow id):

- :mod:`.review` — ``pull_request`` ``opened`` + ``issue_comment``
  ``created`` (``@<app_slug> review``) → ``reviewWorkflowV2``.
- :mod:`.repair` — repair-and-publish follow-up dispatched after a
  comment-triggered review.
- :mod:`.types` — the trigger contract (acks, payload projections,
  comment-trigger models).
- :mod:`.comment` — pure comment-trigger logic (validation,
  classification, incremental-re-review diff-base).
- :mod:`._common` — shared run-environment edge helpers (LLM/sandbox
  ctx resolution, installation→user and repo lookups).

Conventions (same as the adapters this package was copied from):

- Every expected outcome returns an ack model; adapters never raise
  for business outcomes (infrastructure failures propagate so GitHub
  redelivers).
- DB access uses the caller's :class:`AsyncSession` (I/O at the edge).
- Webhook handlers import the adapters lazily (deferred, cycle
  avoidance) — never import this package at module level from
  :mod:`app.services.github.webhook.handlers`.
"""

from __future__ import annotations

from app.workflows.triggers.repair import triggerRepairAfterReview
from app.workflows.triggers.review import (
    handleIssueCommentCreated,
    handlePullRequestOpened,
)
from app.workflows.triggers.types import ReviewTriggerAck

__all__ = [
    "ReviewTriggerAck",
    "handleIssueCommentCreated",
    "handlePullRequestOpened",
    "triggerRepairAfterReview",
]
