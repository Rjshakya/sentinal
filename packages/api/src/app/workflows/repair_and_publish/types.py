"""Serializable contract of the repair-and-publish workflow.

This module owns the models that cross the DBOS boundary, so they are
plain Pydantic ``BaseModel`` subclasses carrying only JSON-serializable
data. Ids are **branded types** from :mod:`app.utils.branded` (erase at
runtime; enforced statically by pyright).

Design notes:

- :class:`RepairAndPublishWorkflowCtx` — the resolved run environment
  (LLM + sandbox configuration), built at the edge next to the input.
  Mirrors :class:`app.workflows.review.types.ReviewWorkflowCtx`.
- :class:`RepairAndPublishWorkflowInput` — the workflow's only input:
  the ``review`` lifecycle row whose unpushed summary + comments should
  be repaired and pushed to GitHub.
- :class:`CommentRow` — one saved comment row with its DB id. The
  repair agent edits only the anchors (``fileName`` / ``side`` /
  ``fromLine`` / ``toLine``); body + severity are final.
- :class:`UnpublishedReview` — the loaded, serializable run data: the
  review identity, the resolved repo / installation, the saved summary
  + verdict, and the ACTIVE comment rows (content untouched, in
  insertion order, each carrying its row id).
- :class:`PublishedReview` — the outcome of the repair agent: the
  posted GitHub review id (summary + verdict + comments, one atomic
  review POST), the comment rows GitHub accepted (all rows of the
  successful review POST), the rows that were never posted, and how
  many publish attempts were used.
- :class:`RepairAndPublishResult` — the workflow result: why the
  workflow finished (posted / skipped / post failed) plus the ids that
  landed.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.services.llm.types import LLMCtx
from app.services.sandbox.types import SandboxCtx
from app.utils.branded import (
    CommitId,
    InstallationId,
    PRNumber,
    RepoId,
    RepoName,
    RepoOwner,
    ReviewRowId,
    UserId,
)
from app.utils.schema import CommentSeverityStr, CommentSideStr, ReviewVerdictStr


class RepairAndPublishWorkflowCtx(BaseModel):
    """Resolved run environment: LLM + sandbox configuration.

    Serialized across the DBOS boundary with
    :class:`RepairAndPublishWorkflowInput`. Assembled at the edge from
    the user's stored ``llm_configs`` row (or settings) and the
    settings-driven sandbox defaults — the same builders the review
    triggers use. Frozen because the workflow never reassigns it; the
    mutable :class:`SandboxCtx` handle travels as a step return value
    after the create-sandbox step fills ``sandboxId``.
    """

    model_config = ConfigDict(frozen=True)

    llmCtx: LLMCtx
    """The run's chat-model configuration (per-user or settings fallback)."""

    sandboxCtx: SandboxCtx
    """The run's sandbox configuration; ``sandboxId`` is filled by the
    create-sandbox step and threaded back through the workflow."""


class RepairAndPublishWorkflowInput(BaseModel):
    """Everything the repair-and-publish workflow needs: the review id."""

    model_config = ConfigDict(frozen=True)

    commitId: str
    """The ``review`` lifecycle row whose unpushed summary + comments
    should be repaired and pushed to GitHub."""


class CommentRow(BaseModel):
    """One saved comment row, carrying its DB id through the repair.

    The agent may correct ONLY the anchors (``fileName`` / ``side`` /
    ``fromLine`` / ``toLine``) so GitHub accepts the payload; the body
    and severity are final and must round-trip unchanged.
    """

    model_config = ConfigDict(frozen=True)

    commentId: str
    """The local ``code_comments.id`` of the saved comment row."""
    fileName: str
    """Path of the file relative to the repo root, exactly as it
    appears in the diff header."""
    fromLine: int
    """First line of the comment range (1-based; may be corrected)."""
    toLine: int
    """Last line of the comment range (1-based; may be corrected)."""
    side: CommentSideStr
    """'RIGHT' for the new side of the diff, 'LEFT' for the old."""
    severity: CommentSeverityStr
    """The saved severity — final, never edited."""
    body: str
    """The saved comment text — final, never edited."""
    nodeType: str | None = None
    """Optional free-form label for the anchored symbol (kept for the
    dashboard; the agent ignores it)."""


class UnpublishedReview(BaseModel):
    """Loaded, serializable run data for one publish attempt.

    The summary and comments are the saved pipeline output, verbatim —
    the repair agent may only fix anchors, never content.
    """

    model_config = ConfigDict(frozen=True)

    reviewId: ReviewRowId
    userId: UserId
    repoId: RepoId
    prNumber: PRNumber
    commitId: CommitId
    """Head commit the review was run against; anchors the GitHub post."""
    baseSha: str | None = None
    """The PR's true base sha (``review.base_sha``); the split diff is
    produced from the fetched PR diff, so this is kept for identity
    only."""
    repoOwner: RepoOwner
    repoName: RepoName
    installationId: InstallationId
    summary: str
    verdict: ReviewVerdictStr
    comments: list[CommentRow]
    """ACTIVE comment rows without a ``github_comment_id``, in
    insertion order, each carrying its row id."""


class PublishedReview(BaseModel):
    """Outcome of the repair agent: what landed on GitHub and what did
    not.

    ``postedComments`` are the rows GitHub accepted — because the
    review POST is atomic, that is exactly the tool call's input on the
    successful call (no per-comment fetch). ``leftComments`` are the
    rows that were never posted (agent dropped them or they stayed
    invalid after the retry budget).
    """

    model_config = ConfigDict(frozen=True)

    githubReviewId: int
    """The posted GitHub PR review id — written onto the ``review`` and
    ``review_summaries`` back-links by the save step."""
    postedComments: list[CommentRow]
    """The comment rows that landed on GitHub (the successful atomic
    POST's input), in original insertion order."""
    leftComments: list[CommentRow]
    """The comment rows that were never posted — downstream deletes
    these rows from the DB."""
    attempts: int = 0
    """How many ``publish_to_github`` tool calls were made."""


RepairAndPublishReason = Literal["posted", "skipped", "post_failed"]
"""Why the workflow finished: it posted, it skipped (no unpublished
review exists for the run), or the repair agent published nothing."""


class RepairAndPublishResult(BaseModel):
    """Workflow result: what happened and where the ids landed."""

    posted: bool
    reason: RepairAndPublishReason
    githubReviewId: int | None = None
    commentCount: int = 0
    attempts: int = 0
    error: str | None = None


__all__ = [
    "CommentRow",
    "PublishedReview",
    "RepairAndPublishReason",
    "RepairAndPublishResult",
    "RepairAndPublishWorkflowCtx",
    "RepairAndPublishWorkflowInput",
    "UnpublishedReview",
]
