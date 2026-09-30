"""Durable boundary contract: strictly-typed events and results.

Two durable functions, no branching:

- ``reviewOpenedHandler`` takes :class:`OpenedDurableEvent`.
- ``reviewCommentHandler`` takes :class:`CommentDurableEvent`.

``payload`` is the only untyped field (raw GitHub JSON). Each handler
validates it once at the start into ``PRPayload`` / ``CommentTriggerInput``
and validates its result once at the end into the ``ReviewSkipped`` /
``ReviewCompleted`` / ``ReviewFailed`` union. Nothing in between uses
``dict[str, Any]``.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


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
    """What the comment path sends to the repair durable function."""

    model_config = ConfigDict(frozen=True)

    delivery: str
    pr_number: int = Field(ge=1)
    commit_id: str = Field(min_length=7, max_length=64)
    execution_name: str
    review_payload: dict = Field(
        default_factory=dict,
        description="Raw GitHub payload (for owner/repo/installation id).",
    )


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


__all__ = [
    "CommentDurableEvent",
    "DurableInvokeResult",
    "DurableRepairEvent",
    "OpenedDurableEvent",
    "ReviewCompleted",
    "ReviewFailed",
    "ReviewSkipped",
]
