"""Fresh v3 review contract: shared input, chained I/O, verdict rule.

The three agent steps form a dependent chain — each step's return is
the next step's input::

    planPath: PlanFilePath = await runPlanner(...)
    review: Review          = await runReviewer(planPath, ...)
    result: PostResult      = await postReview(review, ...)

``PlanFilePath`` is the only untyped handoff: pi reads the plan from
disk, so the host passes the sandbox-absolute path and the prompt
points at it. Everything downstream of it is a validated value.
"""

from __future__ import annotations

from typing import Literal, NewType

from pydantic import BaseModel, ConfigDict, Field

from app.services.pi_harness.types import PiSessionCost
from app.utils.branded import (
    CommitId,
    InstallationId,
    PRNumber,
    PrRowId,
    RepoId,
    RepoName,
    RepoOwner,
    ReviewRowId,
    UserId,
)

PlanFilePath = NewType("PlanFilePath", str)
"""Sandbox-absolute path of the validated ``plan.jsonl`` (``getPlanFile``)."""

ReviewSeverity = Literal["P1_CRITICAL", "P2_WARNING", "P3_NITPICK"]
"""Comment severity levels, matching the ``CommentSeverity`` enum names."""

ReviewSide = Literal["LEFT", "RIGHT"]
"""Diff side a comment anchors to, matching the ``CommentSide`` enum names."""

ReviewVerdict = Literal["APPROVE", "COMMENT", "REQUEST_CHANGES"]
"""Review verdicts, matching GitHub's review-event values verbatim."""


class ReviewV3Input(BaseModel):
    """Everything one v3 review run needs (pure data, no clients)."""

    model_config = ConfigDict(frozen=True)

    userId: UserId
    repoId: RepoId
    repoOwner: RepoOwner
    repoName: RepoName
    ghRepoId: int
    prNumber: PRNumber
    baseSha: str = Field(min_length=1)
    headSha: CommitId
    diffBaseSha: CommitId | None = None
    installationId: InstallationId | None = None
    trigger: str = "opened"


class UpdateDbStateResult(BaseModel):
    """Row ids created/linked by the single-transaction db step."""

    model_config = ConfigDict(frozen=True)

    prRowId: PrRowId
    reviewRowId: ReviewRowId


class CloneResult(BaseModel):
    """The tree is checked out at the reviewed head."""

    model_config = ConfigDict(frozen=True)

    repoDir: str
    headSha: str


class IndexResult(BaseModel):
    """The tree is indexed: counts parsed from the index summary."""

    model_config = ConfigDict(frozen=True)

    files: int
    nodes: int
    edges: int


class DiffResult(BaseModel):
    """The diff was written; ``fetchFailed`` records a tolerated fetch."""

    model_config = ConfigDict(frozen=True)

    diffFile: str
    fetchFailed: bool


class SplitSummary(BaseModel):
    """Tiny parsed split summary: the chunks live in the sandbox, not here."""

    model_config = ConfigDict(frozen=True)

    overviewWritten: bool
    filesChanged: int
    skipped: list[str]


class ReviewComment(BaseModel):
    """One validated inline finding from ``review.jsonl``."""

    model_config = ConfigDict(frozen=True)

    file: str = Field(min_length=1, max_length=1024)
    fromLine: int = Field(ge=1)
    toLine: int = Field(ge=1)
    side: ReviewSide
    severity: ReviewSeverity
    body: str = Field(min_length=1)


class SummaryFile(BaseModel):
    """Minimal contract of ``summary.jsonl``: the walkthrough markdown."""

    model_config = ConfigDict(extra="ignore")

    summary: str


class ReviewFile(BaseModel):
    """Minimal contract of ``review.jsonl``: the inline findings."""

    model_config = ConfigDict(extra="ignore")

    comments: list[ReviewComment] = Field(default_factory=list)


class Review(BaseModel):
    """Merged review outcome: walkthrough + verdict + findings + cost."""

    model_config = ConfigDict(frozen=True)

    summary: str
    verdict: ReviewVerdict
    comments: list[ReviewComment] = Field(default_factory=list)
    cost: PiSessionCost = Field(default_factory=PiSessionCost)


class PostResult(BaseModel):
    """Outcome of the GitHub post (best-effort: never fails the review)."""

    model_config = ConfigDict(frozen=True)

    posted: bool
    githubReviewId: int | None = None
    githubCommentIds: list[int] = Field(default_factory=list)
    error: str | None = None


def workflowIdFor(*, ghRepoId: int, prNumber: int, headSha: str) -> str:
    """Build the deterministic execution name for one review run."""
    return f"review-v3:{ghRepoId}:{prNumber}:{headSha[:7]}"


def verdictFor(comments: list[ReviewComment]) -> ReviewVerdict:
    """Recompute the verdict deterministically from comment severities."""
    if any(comment.severity == "P1_CRITICAL" for comment in comments):
        return "REQUEST_CHANGES"
    if comments:
        return "COMMENT"
    return "APPROVE"


__all__ = [
    "CloneResult",
    "DiffResult",
    "IndexResult",
    "PlanFilePath",
    "PostResult",
    "Review",
    "ReviewComment",
    "ReviewFile",
    "ReviewSeverity",
    "ReviewSide",
    "ReviewV3Input",
    "ReviewVerdict",
    "SplitSummary",
    "SummaryFile",
    "UpdateDbStateResult",
    "verdictFor",
    "workflowIdFor",
]
