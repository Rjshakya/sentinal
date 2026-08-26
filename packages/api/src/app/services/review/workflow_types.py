"""Serializable Pydantic models for the review workflow inputs and outputs.

DBOS serializes workflow and step I/O through the system database, so every
boundary type is a Pydantic ``BaseModel`` with ``frozen=True``. This module
owns those types so they can be imported without pulling in the workflow
body, the DBOS decorators, or any of the step implementations.

Types:

- :class:`ReviewWorkflowInput` — top-level input of the ``review_workflow``.
- :class:`PostReviewInput`     — top-level input of ``post_review_to_github_workflow``.
- :class:`ReviewRunResult`     — top-level return of the ``review_workflow``.
- :class:`PostReviewResult`    — top-level return of the GitHub post workflow.
- :class:`RepoSnapshot`        — serialisable subset of :class:`app.models.repo.Repo`,
  carried across the workflow boundary (DBOS cannot persist ORM objects).
- :class:`ResolvedSandbox`     — serialisable subset of a resolved sandbox
  (``sandbox_id`` + ``sandbox_name``) used as the workflow's sandbox handle.
- :class:`TotalUsages`         — per-model token counter (TypedDict, not Pydantic).
- :class:`TotalUsagesPerPR`    — per-run aggregated token usage envelope
  (TypedDict, not Pydantic) keyed by model name.
"""

from __future__ import annotations

from typing import TypedDict

from pydantic import BaseModel, ConfigDict, Field

from app.core.llm import LLMConfig
from app.models.enums import PRStatus
from app.services.agent.models import ReviewResult


class PRSizeStats(TypedDict):
    """GitHub PR size stats carried from the trigger payload.

    ``additions`` / ``deletions`` are the number of added / removed
    lines; ``changed_files`` is the number of files touched by the PR.
    Every trigger populates this from the GitHub payload (the
    ``pull_request`` webhook carries them directly; the comment-trigger
    path reads them from ``GET /repos/.../pulls/{number}``).

    These drive the per-run model/tool call limits via
    :func:`app.services.review.helpers.compute_review_limits`.
    """

    additions: int
    deletions: int
    changed_files: int


def _empty_pr_size() -> PRSizeStats:
    """A zero-size :class:`PRSizeStats` for inputs without size data."""
    return PRSizeStats(additions=0, deletions=0, changed_files=0)


class ReviewWorkflowInput(BaseModel):
    """Everything needed to durably review one PR."""

    model_config = ConfigDict(frozen=True)

    user_id: str
    gh_repo_id: int
    pr_id: int
    pr_number: int
    branch: str
    default_branch: str | None = None
    base_sha: str
    head_sha: str
    head_branch: str
    author: str
    body: str
    title: str
    status: PRStatus
    trigger: str = "opened"
    llm_config: LLMConfig
    post_to_github: bool
    github_installation_id: int
    """GitHub installation id for this run.

    Used to mint the installation token that clones the repo into the
    per-run sandbox (:func:`app.services.review.steps.clone_repo.clone_repo_step`)
    and to post the review to GitHub. Both triggers supply it: the
    ``pull_request`` webhook adapter (``app.services.review.webhook``)
    and the comment-trigger path
    (``app.services.pr_issue_comment.helpers``).
    """
    pr_size: PRSizeStats = Field(default_factory=_empty_pr_size)
    diff_base_sha: str | None = None
    """Incremental-re-review override for the git-diff range.

    When set, the review diffs ``diff_base_sha...head_sha`` instead of
    ``base_sha...head_sha`` — the comment-trigger path sets it to the
    last successfully reviewed head so a re-review covers only the
    commits pushed since the previous run. ``base_sha`` itself always
    keeps the PR's true base: the ``pull_requests`` and ``review``
    rows record it unchanged, and only the diff range narrows.
    """
    diff_base_sha: str | None = None


class PostReviewInput(BaseModel):
    """Input for the independent GitHub post workflow."""

    model_config = ConfigDict(frozen=True)

    repo_id: str
    pr_id: str
    commit_id: str
    github_installation_id: int
    repo_owner: str
    repo_name: str
    pr_number: int
    review: ReviewResult


class ReviewRunResult(BaseModel):
    """What the main review workflow returns."""

    model_config = ConfigDict(frozen=True)

    pr_id: str
    commit_id: str
    review: ReviewResult
    usages: TotalUsagesPerPR


class PostReviewResult(BaseModel):
    """What the GitHub post workflow returns."""

    model_config = ConfigDict(frozen=True)

    posted: bool
    github_review_id: int | None = None
    error: str | None = None


class RepoSnapshot(BaseModel):
    """Serializable subset of :class:`app.models.repo.Repo`."""

    model_config = ConfigDict(frozen=True)

    id: str
    repo_name: str
    repo_owner: str
    default_branch: str | None = None


class SandboxMeta(BaseModel):
    """Serializable subset of a resolved sandbox."""

    model_config = ConfigDict(frozen=True)

    sandbox_id: str
    sandbox_name: str


# --------------------------------------------------------------------------- #
# Token usage envelopes                                                         #
# --------------------------------------------------------------------------- #


class InputTokenDetails(TypedDict, total=False):
    """Cache-related fields on the input token side.

    Mirrors the JSONB column shape on
    :class:`app.models.review_usage.ReviewUsage.input_token_details`.
    Both fields are optional because not every provider surfaces
    cache metadata.
    """

    cache_read: int | None
    cache_creation: int | None


class TotalUsages(TypedDict):
    """Per-model aggregated token counts for one review run.

    ``input_token_details`` is optional and may be empty when the
    underlying provider does not report cache metadata.
    """

    input_tokens: int
    output_tokens: int
    total_tokens: int
    input_token_details: InputTokenDetails


class TotalUsagesPerPR(TypedDict):
    """Per-run aggregated token usage, keyed by model name.

    The envelope is built by
    :func:`app.services.review.steps.invoke_agent.combine_agent_outcomes`
    while the two agent steps fan out, then carried through the
    workflow boundary to be persisted by
    :func:`app.services.review.steps.persist_usage.persist_review_usage_tx`.
    """

    pr_number: int
    head_sha: str
    repo_id: str
    user_id: str
    usages: dict[str, TotalUsages]


__all__ = [
    "InputTokenDetails",
    "PRSizeStats",
    "PostReviewInput",
    "PostReviewResult",
    "RepoSnapshot",
    "ReviewRunResult",
    "ReviewWorkflowInput",
    "SandboxMeta",
    "TotalUsages",
    "TotalUsagesPerPR",
]
