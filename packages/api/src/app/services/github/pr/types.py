"""PR sub-service types: ctx + draft/result models.

This module owns the contract of the pr sub-service: the :class:`PRCtx`
(identity + injected client), the :class:`PRState` snapshot of a pull
request as read from the GitHub API, and the fresh draft models
(:class:`PRReviewDraft` / :class:`PRCommentDraft`) the post path
consumes.

Naming convention: this package intentionally uses **camelCase**
identifiers — the same convention as :mod:`app.services.llm` and
:mod:`app.services.sandbox`. Ids that are also identifiers (id, ctx)
keep their single-word lowercase form.

Design notes:

- :class:`PRCtx` is a plain Pydantic model carrying identity plus the
  installation-scoped githubkit client, minted by the ctx factory
  (:func:`app.services.github.pr.service.createPRCtx`) at the edge.
  Not serializable — tests build the ctx directly with a mock client.
- Ids are **branded types** (``NewType`` over ``str`` / ``int`` from
  :mod:`app.utils.branded`): they erase at runtime (Pydantic validation
  is unaffected) but pyright enforces the branding statically, so a
  bare ``int`` cannot accidentally flow into a ctx.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from githubkit import GitHub
from pydantic import BaseModel, ConfigDict, Field

from app.utils.branded import (
    CommitId,
    InstallationId,
    PRNumber,
    RepoName,
    RepoOwner,
    UserId,
)

PRVerdict = Literal["APPROVE", "REQUEST_CHANGES", "COMMENT"]
"""GitHub review event values — these match GitHub's API verbatim."""

ReactionContent = Literal[
    "+1", "-1", "laugh", "confused", "heart", "hooray", "rocket", "eyes"
]
"""GitHub issue-comment reaction contents."""


class PRCtx(BaseModel):
    """Identity of one pull request under one installation + its client."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    userId: UserId
    installationId: InstallationId
    owner: RepoOwner
    repo: RepoName
    prNumber: PRNumber
    commitId: CommitId | None = None
    """Head commit the review targets; required by :func:`postReview`."""
    client: GitHub


class PRState(BaseModel):
    """Snapshot of a PR as read from the GitHub API."""

    ghPrId: int
    state: str
    merged: bool
    title: str
    body: str
    author: str
    baseBranch: str
    baseSha: str
    headBranch: str
    headSha: str
    additions: int = 0
    deletions: int = 0
    changedFiles: int = 0


class PRCommentDraft(BaseModel):
    """One inline review comment draft."""

    fileName: str
    line: int
    side: str
    body: str


class PRReviewDraft(BaseModel):
    """Fresh review payload: verdict, summary, inline comments."""

    verdict: PRVerdict
    summary: str
    comments: list[PRCommentDraft] = Field(default_factory=list)


PullListState = Literal["open", "closed", "all"]
"""``GET /pulls`` state filter — passed straight to the GitHub API."""


class PRListItem(BaseModel):
    """One row of ``GET /pulls`` — header fields only, no patch/diff."""

    number: int
    title: str
    body: str = ""
    author: str
    authorAvatar: str | None = None
    state: str
    draft: bool = False
    baseBranch: str
    headBranch: str
    headSha: str
    createdAt: datetime | None = None
    updatedAt: datetime | None = None
    closedAt: datetime | None = None
    mergedAt: datetime | None = None
    htmlUrl: str | None = None


class PRCommitItem(BaseModel):
    """One row of ``GET /pulls/{n}/commits``."""

    sha: str
    message: str
    authorLogin: str
    authorAvatar: str | None = None
    authorName: str
    date: datetime | None = None
    htmlUrl: str | None = None


class PRFileItem(BaseModel):
    """One row of ``GET /pulls/{n}/files`` — ``patch`` verbatim from GitHub.

    GitHub omits ``patch`` for binary / too-large diffs; that ``None``
    is passed through untouched (no server-side truncation).
    """

    sha: str
    filename: str
    status: str
    additions: int = 0
    deletions: int = 0
    changes: int = 0
    patch: str | None = None
    blobUrl: str | None = None
    rawUrl: str | None = None
    previousFilename: str | None = None


class IssueCommentItem(BaseModel):
    """One row of ``GET /issues/{n}/comments`` (Conversation tab)."""

    id: int
    authorLogin: str
    authorAvatar: str | None = None
    body: str
    createdAt: datetime | None = None
    updatedAt: datetime | None = None
    htmlUrl: str | None = None


class ReviewCommentItem(BaseModel):
    """One inline review comment (Conversation tab)."""

    id: int
    authorLogin: str
    authorAvatar: str | None = None
    body: str
    path: str
    line: int | None = None
    side: str | None = None
    commitId: str | None = None
    createdAt: datetime | None = None
    updatedAt: datetime | None = None
    htmlUrl: str | None = None
    reviewId: int | None = None


class PRReviewItem(BaseModel):
    """One submitted PR review (Conversation tab)."""

    id: int
    authorLogin: str
    authorAvatar: str | None = None
    state: str
    body: str = ""
    commitId: str | None = None
    submittedAt: datetime | None = None
    htmlUrl: str | None = None


__all__ = [
    "PRCommentDraft",
    "PRCommitItem",
    "PRCtx",
    "PRFileItem",
    "PRListItem",
    "PRReviewDraft",
    "PRReviewItem",
    "PRState",
    "PRVerdict",
    "PullListState",
    "IssueCommentItem",
    "ReactionContent",
    "ReviewCommentItem",
]