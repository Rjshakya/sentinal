"""Serializable contract of the review workflow: ctx, input, results.

This module owns the models that cross the DBOS boundary, so they are
plain Pydantic ``BaseModel`` subclasses (``frozen=True``) carrying only
JSON-serializable data. Ids are **branded types** from
:mod:`app.utils.branded` (erase at runtime; enforced statically by
pyright).

Design notes:

- :class:`ReviewWorkflowCtx` — the resolved run environment, built at
  the edge (the webhook adapter) and passed to
  :func:`app.workflows.review.workflow.reviewWorkflow` next to the
  input. It carries the per-user :class:`LLMCtx` (from
  :mod:`app.services.llm`) and the :class:`SandboxCtx` (from
  :mod:`app.services.sandbox`) — both serializable, so the ctx crosses
  the workflow boundary as pure data.
- :class:`ReviewWorkflowInput` — the PR-specific trigger data (ids,
  SHAs, PR metadata, size stats). The trigger-specific knobs
  (``postToGithub``, ``diffBaseSha``) live here, not on the ctx.
- The comment-trigger contract (:class:`CommentTriggerInput`,
  :class:`ClassifyCommentResult`, :class:`LastReviewSnapshot`) — the
  typed payload view, the classification outcome, and the previous-run
  snapshot consumed by
  :func:`app.workflows.review.helpers.effectiveDiffBase`.
- Result projections (:class:`RepoSnapshot`, :class:`ReviewRunResult`,
  :class:`PostReviewResult`) and the token-usage envelopes mirror the
  legacy shapes so the persistence layer translates them unchanged.
"""

from __future__ import annotations

from datetime import datetime
from typing import TypedDict

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import PRStatus
from app.services.llm.types import LLMCtx
from app.services.sandbox.types import SandboxCtx
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


class ReviewWorkflowCtx(BaseModel):
    """Resolved run environment: LLM + sandbox configuration.

    Serialized across the DBOS boundary with :class:`ReviewWorkflowInput`.
    Assembled at the edge by the webhook adapter from the user's stored
    ``llm_configs`` row (or settings) and the settings-driven sandbox
    defaults. Frozen because the workflow never reassigns it — the
    mutable :class:`SandboxCtx` handle travels as a step return value
    after the create step fills ``sandboxId``.
    """

    model_config = ConfigDict(frozen=True)

    llmCtx: LLMCtx
    """The run's chat-model configuration (per-user or settings fallback)."""

    sandboxCtx: SandboxCtx
    """The run's sandbox configuration; ``sandboxId`` is filled by the
    create-sandbox step and threaded back through the workflow."""


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


class CommentTriggerInput(BaseModel):
    """Flat, typed view of a verified ``issue_comment`` payload.

    Every field is required; the trigger adapter
    (:func:`app.workflows.review.helpers.validateCommentPayload`)
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


class RepoSnapshot(BaseModel):
    """Serializable subset of :class:`app.models.repo.Repo`."""

    model_config = ConfigDict(frozen=True)

    id: RepoId
    repoOwner: RepoOwner
    repoName: RepoName
    defaultBranch: str | None = None


class ReviewLimits(BaseModel):
    """Per-run model/tool call limits for the review agents.

    A Pydantic model (not a dataclass) so it survives DBOS
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
    "ClassifyCommentResult",
    "CommentTriggerInput",
    "InputTokenDetails",
    "LastReviewSnapshot",
    "PRSizeStats",
    "PostReviewResult",
    "RepoSnapshot",
    "ReviewLimits",
    "ReviewRunResult",
    "ReviewWorkflowCtx",
    "ReviewWorkflowInput",
    "SplitDiffResult",
    "TotalUsages",
    "TotalUsagesPerPR",
    "emptyPrSize",
]
