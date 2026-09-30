"""Serializable contract of the review workflow: input, snapshots, results.

Plain Pydantic ``BaseModel`` subclasses (``frozen=True``) carrying only
JSON-serializable data. Ids are **branded types** from
:mod:`app.utils.branded` (erase at runtime; enforced statically by
pyright). The trigger contract (``CommentTriggerInput`` /
``ClassifyCommentResult`` / ``LastReviewSnapshot``) lives in
:mod:`app.workflows.triggers.types` — this module does not duplicate it.
"""

from __future__ import annotations

from typing import TypedDict

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import PRStatus
from app.utils.branded import (
    CommitId,
    InstallationId,
    PRNumber,
    PrRowId,
    RepoId,
    RepoName,
    RepoOwner,
    UserId,
)
from app.utils.schema import ReviewResult


class PRSizeStats(TypedDict):
    """GitHub PR size stats driving the per-run agent call limits."""

    additions: int
    deletions: int
    changedFiles: int


def emptyPrSize() -> PRSizeStats:
    """A zero-size :class:`PRSizeStats` for inputs without size data."""
    return PRSizeStats(additions=0, deletions=0, changedFiles=0)


class ReviewWorkflowInput(BaseModel):
    """Everything PR-specific needed to durably review one PR."""

    model_config = ConfigDict(frozen=True)

    userId: UserId
    ghRepoId: int
    ghPrId: int
    prNumber: PRNumber
    baseBranch: str
    defaultBranch: str | None = None
    baseSha: str
    headSha: CommitId
    headBranch: str
    author: str
    title: str
    body: str
    status: PRStatus
    trigger: str = "opened"
    postToGithub: bool = False
    githubInstallationId: InstallationId | None = None
    prSize: PRSizeStats = Field(default_factory=emptyPrSize)
    diffBaseSha: CommitId | None = None
    """Incremental-re-review override for the git-diff range.

    When set, the diff covers ``diffBaseSha...headSha`` instead of
    ``baseSha...headSha`` — the comment-trigger path sets it to the
    last successfully reviewed head. ``baseSha`` itself always keeps
    the PR's true base on the lifecycle rows.
    """


class RepoSnapshot(BaseModel):
    """Serializable subset of :class:`app.models.repo.Repo`."""

    model_config = ConfigDict(frozen=True)

    id: RepoId
    repoOwner: RepoOwner
    repoName: RepoName
    defaultBranch: str | None = None


class ReviewLimits(BaseModel):
    """Per-run model/tool call limits for the review agents.

    A Pydantic model (not a dataclass) so it survives durable
    serialization across the step boundary.
    """

    model_config = ConfigDict(frozen=True)

    modelCallRunLimit: int
    toolCallRunLimit: int


class ReviewRunResult(BaseModel):
    """What the main review workflow returns on success."""

    model_config = ConfigDict(frozen=True)

    prRowId: PrRowId
    commitId: CommitId
    review: ReviewResult
    usages: TotalUsagesPerPR


class PostReviewResult(BaseModel):
    """Outcome of the GitHub post step.

    ``posted=False`` with ``error`` means the post failed terminally
    (4xx) — the local review still completed, so the workflow does not
    fail over it.
    """

    model_config = ConfigDict(frozen=True)

    posted: bool
    githubReviewId: int | None = None
    githubCommentIds: list[int] = Field(default_factory=list)
    error: str | None = None


class SplitDiffResult(TypedDict):
    """The tiny summary JSON the in-sandbox split script prints on stdout.

    ``overviewWrittten`` — whether ``overview.md`` was written.
    ``filesChanged`` — number of per-file chunks created in
    ``splitted_diffs/``. ``skipped`` — paths that appeared in the diff
    but were not split (binary files, or rename-only sections with no
    hunks).
    """

    overview_written: bool
    files_changed: int
    skipped: list[str]


# --------------------------------------------------------------------------- #
# Token usage envelopes                                                         #
# --------------------------------------------------------------------------- #


class InputTokenDetails(TypedDict, total=False):
    """Cache-related fields on the input-token side (JSONB column shape)."""

    cache_read: int | None
    cache_creation: int | None


class TotalUsages(TypedDict):
    """Per-model aggregated token counts for one review run."""

    input_tokens: int
    output_tokens: int
    total_tokens: int
    input_token_details: InputTokenDetails


class TotalUsagesPerPR(TypedDict):
    """Per-run aggregated token usage, keyed by model name."""

    pr_number: int
    head_sha: str
    repo_id: str
    user_id: str
    usages: dict[str, TotalUsages]


__all__ = [
    "InputTokenDetails",
    "PRSizeStats",
    "PostReviewResult",
    "RepoSnapshot",
    "ReviewLimits",
    "ReviewRunResult",
    "ReviewWorkflowInput",
    "SplitDiffResult",
    "TotalUsages",
    "TotalUsagesPerPR",
    "emptyPrSize",
]
