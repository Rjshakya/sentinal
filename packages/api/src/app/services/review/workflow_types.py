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
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from app.core.llm import LLMProviderStr
from app.models.enums import PRStatus
from app.services.agent.models import ReviewResult


class ReviewWorkflowInput(BaseModel):
    """Everything needed to durably review one PR."""

    model_config = ConfigDict(frozen=True)

    user_id: str
    gh_repo_id: int
    pr_id: int
    pr_number: int
    branch: str
    base_sha: str
    head_sha: str
    head_branch: str
    author: str
    body: str
    title: str
    status: PRStatus
    llm_baseurl: str | None
    llm_api_key: str
    llm_model: str
    provider: LLMProviderStr
    post_to_github: bool
    github_installation_id: int | None = None


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


class ResolvedSandbox(BaseModel):
    """Serializable subset of a resolved sandbox."""

    model_config = ConfigDict(frozen=True)

    sandbox_id: str
    sandbox_name: str


__all__ = [
    "PostReviewInput",
    "PostReviewResult",
    "RepoSnapshot",
    "ResolvedSandbox",
    "ReviewRunResult",
    "ReviewWorkflowInput",
]
