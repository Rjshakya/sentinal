"""Durable boundary contract: strictly-typed events and results.

Three durable functions, no branching:

- ``reviewOpenedHandler`` takes :class:`OpenedDurableEvent`.
- ``reviewCommentHandler`` takes :class:`CommentDurableEvent`.
- ``repair_durable_handler`` takes :class:`DurableRepairEvent`.

``payload`` is the only untyped field (raw GitHub JSON). Each handler
validates it once at the start into ``PRPayload`` / ``CommentTriggerInput``
and validates its result once at the end into the ``ReviewSkipped`` /
``ReviewCompleted`` / ``ReviewFailed`` union. Nothing in between uses
``dict[str, Any]``.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

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


class OpenedDurableEvent(BaseModel):
    """Input for the PR-opened durable function."""

    model_config = ConfigDict(frozen=True)

    delivery: str = Field(description="X-GitHub-Delivery id.")
    execution_name: str = Field(description="Deterministic execution name.")
    payload: dict = Field(description="Verified raw GitHub pull_request payload.")


class CommentDurableEvent(BaseModel):
    """Input for the comment-trigger durable function."""

    model_config = ConfigDict(frozen=True)

    delivery: str = Field(description="X-GitHub-Delivery id.")
    execution_name: str = Field(description="Deterministic execution name.")
    payload: dict = Field(description="Verified raw GitHub issue_comment payload.")


class DurableRepairEvent(BaseModel):
    """Input for the repair durable function (one repair per review commit)."""

    model_config = ConfigDict(frozen=True)

    delivery: str
    pr_number: int = Field(ge=1)
    commit_id: str = Field(min_length=7, max_length=64)
    execution_name: str


class ReviewSkipped(BaseModel):
    """Handler exit when the run never starts (guard-clause return)."""

    model_config = ConfigDict(frozen=True)

    accepted: Literal[False] = False
    delivery: str
    skip_reason: str


class ReviewCompleted(BaseModel):
    """Handler exit when the agent phase finishes."""

    model_config = ConfigDict(frozen=True)

    accepted: Literal[True] = True
    phase: Literal["review-complete"] = "review-complete"
    delivery: str
    execution_name: str
    workflow_id: str
    review_id: str
    repo_id: str
    pr_number: int
    head_sha: str
    base_sha: str
    diff_base_sha: str | None = None
    user_id: str
    verdict: str
    comment_count: int
    posted: bool
    github_review_id: int | None = None


class ReviewFailed(BaseModel):
    """Handler exit when the agent phase raises."""

    model_config = ConfigDict(frozen=True)

    accepted: Literal[True] = True
    phase: Literal["review-failed"] = "review-failed"
    delivery: str
    execution_name: str
    repo_id: str
    pr_number: int
    head_sha: str
    user_id: str
    error_name: str
    error_message: str


class DurableInvokeResult(BaseModel):
    """Outcome of a best-effort async Invoke (never raises for business)."""

    model_config = ConfigDict(frozen=True)

    invoked: bool
    execution_name: str | None = None
    function_name: str | None = None
    error: str | None = None


class CommentRow(BaseModel):
    """One saved comment row, carrying its DB id through the repair.

    The agent may correct ONLY the anchors (fileName / side / fromLine /
    toLine) so GitHub accepts the payload; body + severity are final.
    """

    model_config = ConfigDict(frozen=True)

    commentId: str
    fileName: str
    fromLine: int
    toLine: int
    side: CommentSideStr
    severity: CommentSeverityStr
    body: str
    nodeType: str | None = None


class UnpublishedReview(BaseModel):
    """Loaded, serializable run data for one repair attempt.

    The summary and comments are the saved pipeline output, verbatim —
    the repair agent may only fix anchors, never content.
    """

    model_config = ConfigDict(frozen=True)

    reviewId: ReviewRowId
    userId: UserId
    repoId: RepoId
    prNumber: PRNumber
    commitId: CommitId
    baseSha: str | None = None
    repoOwner: RepoOwner
    repoName: RepoName
    installationId: InstallationId
    summary: str
    verdict: ReviewVerdictStr
    comments: list[CommentRow]


class PublishedReview(BaseModel):
    """Outcome of the repair agent: what landed on GitHub and what did not.

    The review POST is atomic, so postedComments is exactly the tool
    call's input on the successful call. leftComments were never posted
    and get deleted from the DB.
    """

    model_config = ConfigDict(frozen=True)

    githubReviewId: int
    postedComments: list[CommentRow]
    leftComments: list[CommentRow]
    attempts: int = 0


class RepairSkipped(BaseModel):
    """Repair exit when there is nothing to publish."""

    model_config = ConfigDict(frozen=True)

    accepted: Literal[False] = False
    delivery: str
    skip_reason: str


class RepairCompleted(BaseModel):
    """Repair exit when the agent phase finishes."""

    model_config = ConfigDict(frozen=True)

    accepted: Literal[True] = True
    phase: Literal["repair-complete"] = "repair-complete"
    delivery: str
    execution_name: str
    review_id: str
    pr_number: int
    commit_id: str
    posted: bool
    github_review_id: int | None = None
    posted_count: int = 0
    dropped_count: int = 0
    attempts: int = 0


class RepairFailed(BaseModel):
    """Repair exit when the agent phase raises."""

    model_config = ConfigDict(frozen=True)

    accepted: Literal[True] = True
    phase: Literal["repair-failed"] = "repair-failed"
    delivery: str
    execution_name: str
    review_id: str
    pr_number: int
    commit_id: str
    error_name: str
    error_message: str


__all__ = [
    "CommentDurableEvent",
    "CommentRow",
    "DurableInvokeResult",
    "DurableRepairEvent",
    "OpenedDurableEvent",
    "PublishedReview",
    "RepairCompleted",
    "RepairFailed",
    "RepairSkipped",
    "ReviewCompleted",
    "ReviewFailed",
    "ReviewSkipped",
    "UnpublishedReview",
]
