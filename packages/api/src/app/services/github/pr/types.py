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


__all__ = [
    "PRCommentDraft",
    "PRCtx",
    "PRReviewDraft",
    "PRState",
    "PRVerdict",
    "ReactionContent",
]