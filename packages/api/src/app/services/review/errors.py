"""Typed error variants for the review pipeline.

A closed union so :func:`run_review_pipeline` callers can ``match`` on
every expected failure. Unexpected crashes are caught once at the
orchestrator's outer boundary and converted to
:class:`ReviewAgentCrashed`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Union

from app.services.github.post_review import GitHubPosterError


@dataclass(frozen=True)
class RepoNotFound:
    """The requested repo does not exist in the local repo table."""

    repo_id: str


@dataclass(frozen=True)
class NoActiveSandbox:
    """No active sandbox exists for the (user, repo) pair."""

    user_id: str
    repo_id: str


@dataclass(frozen=True)
class SandboxConnectFailed:
    """An active sandbox row exists but connecting to it failed."""

    user_id: str
    repo_id: str
    sandbox_id: str
    cause: str


@dataclass(frozen=True)
class DiffUnavailable:
    """We could not obtain a unified diff to review."""

    repo_id: str
    base_sha: str
    head_sha: str
    cause: str


@dataclass(frozen=True)
class ReviewAgentCrashed:
    """The review agent raised an unexpected exception."""

    cause: str


@dataclass(frozen=True)
class ReviewAgentReturnedNoStructuredResponse:
    """The agent finished but produced no structured_response."""

    message_kinds: tuple[str, ...]


ReviewPipelineError = Union[
    RepoNotFound,
    NoActiveSandbox,
    SandboxConnectFailed,
    DiffUnavailable,
    ReviewAgentCrashed,
    ReviewAgentReturnedNoStructuredResponse,
    GitHubPosterError,
]
