"""PR ``issue_comment`` trigger pipeline.

This subpackage owns the end-to-end path that turns a user
commenting ``@<app_slug> review`` on a pull request into a
dispatched DBOS review workflow. It is intentionally a sibling of
:mod:`app.services.review` rather than a child, so the review
package keeps a single concern (the review pipeline itself) and
the trigger-specific plumbing lives in one place.

Layout:

- :mod:`.errors`  — typed exception hierarchy
  (:class:`TriggerError`, :class:`TransientTriggerError`,
  :class:`PRFetchError`, :class:`ReactionError`).
- :mod:`.types`   — Pydantic models that cross the workflow
  boundary (:class:`IssueCommentTriggerInput`,
  :class:`ClassifyCommentResult`, :class:`TriggerRunResult`,
  :class:`InstallationSnapshot`, :class:`PRStateSnapshot`).
- :mod:`.helpers` — pure functions (validate / classify / regex
  / authorization / build the inner review input). No I/O, no
  DBOS.
- :mod:`.steps`   — DBOS-wrapped I/O boundaries. One file per
  concern: ``resolve_installation``, ``resolve_repo_id``,
  ``fetch_pr_state``, ``add_reaction``, ``resolve_llm_config``,
  ``build_review_input``, ``dispatch_review``.
- :mod:`.workflow` — :func:`trigger_issue_comment_workflow`. The
  DBOS workflow that sequences the pre-work steps and dispatches
  the inner ``review_workflow``.
- :mod:`.handler` — :func:`handle_issue_comment_created`. The
  router adapter. Never raises; always returns a
  :class:`app.services.review.webhook.WebhookAck`.

Re-exports the workflow + handler + key types so callers do not
need to know the internal layout.
"""

from __future__ import annotations

from app.services.pr_issue_comment.errors import (
    PRFetchError,
    ReactionError,
    TransientTriggerError,
    TriggerError,
)
from app.services.pr_issue_comment.handler import handle_issue_comment_created
from app.services.pr_issue_comment.types import (
    ClassifyCommentResult,
    InstallationSnapshot,
    IssueCommentTriggerInput,
    PRStateSnapshot,
    TriggerRunResult,
)
from app.services.pr_issue_comment.workflow import trigger_issue_comment_workflow

__all__ = [
    "ClassifyCommentResult",
    "InstallationSnapshot",
    "IssueCommentTriggerInput",
    "PRFetchError",
    "PRStateSnapshot",
    "ReactionError",
    "TransientTriggerError",
    "TriggerError",
    "TriggerRunResult",
    "handle_issue_comment_created",
    "trigger_issue_comment_workflow",
]
