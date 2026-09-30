"""Trigger contract: serializable models for the workflow trigger adapters.

All models are plain Pydantic ``BaseModel`` subclasses carrying only
JSON-serializable data. Ids are **branded types** from
:mod:`app.utils.branded` (erase at runtime; enforced statically by
pyright). The workflow contract itself (``ReviewWorkflowCtx`` /
``ReviewWorkflowInput`` / ``PRSizeStats``) stays in
:mod:`app.workflows.review_v2.types` — triggers import it, not duplicate it.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models.enums import PRStatus
from app.utils.branded import (
    CommitId,
    InstallationId,
    PRNumber,
    RepoName,
    RepoOwner,
)
from app.workflows.review_v2.types import PRSizeStats


class ReviewTriggerAck(BaseModel):
    """What a trigger adapter hands back to the webhook handler for logging."""

    accepted: bool
    action: str
    delivery: str
    skip_reason: str | None = None


class PRPayload(BaseModel):
    """Flat, typed projection of a verified ``pull_request`` ``opened`` payload."""

    ghRepoId: int
    ghPrId: int
    number: PRNumber
    baseBranch: str
    defaultBranch: str | None
    baseSha: str
    headBranch: str
    headSha: CommitId
    author: str
    title: str
    body: str
    status: PRStatus
    prSize: PRSizeStats


class CommentTriggerInput(BaseModel):
    """Flat, typed view of a verified ``issue_comment`` payload.

    Every field is required; the trigger adapter
    (:func:`app.workflows.triggers.comment_payload.validateCommentPayload`)
    returns ``None`` when the raw webhook does not satisfy the
    pydantic schema, which the caller folds into a
    ``malformed_payload`` skip.
    """

    model_config = ConfigDict(frozen=True)

    delivery: str
    installationId: InstallationId
    repoOwner: RepoOwner
    repoName: RepoName
    ghRepoId: int
    defaultBranch: str | None = None
    prNumber: PRNumber
    prAuthorLogin: str
    commenterLogin: str
    authorAssociation: str
    commentId: int
    commentBody: str


class ClassifyCommentResult(BaseModel):
    """Outcome of the pure classification helper.

    ``shouldProceed`` is ``True`` iff every check (action / is_pr /
    is_self / has_mention / is_authorized) passed. The first failing
    check sets ``skipReason`` to a stable string the edge can log.
    """

    model_config = ConfigDict(frozen=True)

    shouldProceed: bool
    skipReason: str | None = None


class LastReviewSnapshot(BaseModel):
    """Serializable subset of the latest successful :class:`Review` row.

    Lets the comment trigger decide the git-diff base for an
    incremental re-review: ``commitId`` is the head SHA the previous
    run reviewed; ``baseSha`` is the PR base that run started from
    (kept for observability). Both are the values recorded on the
    ``review`` lifecycle row, never re-fetched from GitHub.
    """

    model_config = ConfigDict(frozen=True)

    commitId: CommitId
    baseSha: str | None = None
    createdAt: datetime


__all__ = [
    "ClassifyCommentResult",
    "CommentTriggerInput",
    "LastReviewSnapshot",
    "PRPayload",
    "ReviewTriggerAck",
]
