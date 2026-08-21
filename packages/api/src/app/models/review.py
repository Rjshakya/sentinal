"""``review`` table — durable per-run record of one review workflow run.

One row per DBOS invocation of ``review_workflow``, keyed by the
deterministic workflow id (``review:{repo_id}:{pr_number}:{head_sha[:7]}``).
Mirrors the workflow lifecycle so the dashboard and analytics can query
review runs — including failures, which currently leave no record beyond
DBOS's own workflow table — without depending on DBOS state.

State machine: ``STARTING`` → ``RUNNING`` → (``SUCCESS`` | ``FAILED``).
Every transition is best-effort: a DB blip never breaks the workflow
itself. The DBOS workflow's own state is the source of truth; this table
is the user-facing mirror.

The LLM columns snapshot the resolved
:class:`app.core.llm.LLMConfig` at run time so failed runs keep their
LLM identity even though no usage/summary rows exist. ``error_context``
carries the JSON payload of :class:`app.services.review.errors.ReviewAgentsInvocationError`
(failed/succeeded agent names, retryable flags, cause) when it was the
failure source.
"""

from __future__ import annotations

import enum
from datetime import UTC, datetime

from sqlalchemy import Column, String, text
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP
from sqlmodel import Field, ForeignKey, SQLModel

from app.utils.util import uuidToStr


class ReviewState(str, enum.Enum):
    """Lifecycle state of a :class:`Review` row.

    Stored as a ``String(16)`` column (the ``IndexRun`` pattern) to
    avoid PG-ENUM ALTER churn.
    """

    STARTING = "STARTING"
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"


class Review(SQLModel, table=True):
    id: str = Field(default_factory=uuidToStr, primary_key=True)

    user_id: str = Field(nullable=False, index=True)
    repo_id: str = Field(
        sa_column_args=(ForeignKey("repo.id", ondelete="CASCADE"),),
        nullable=False,
        index=True,
    )
    gh_repo_id: int = Field(nullable=False)
    pr_id: str = Field(
        sa_column_args=(ForeignKey("pullrequest.id", ondelete="CASCADE"),),
        nullable=False,
        index=True,
    )
    pr_number: int = Field(nullable=False)
    commit_id: str = Field(nullable=False, index=True)
    base_sha: str | None = Field(default=None)

    workflow_id: str = Field(nullable=False, unique=True, index=True)
    trigger: str | None = Field(default=None)

    state: ReviewState = Field(
        default=ReviewState.STARTING,
        sa_column=Column(String(16), nullable=False, index=True),
    )
    comment_count: int | None = Field(default=None)
    github_review_id: str | None = Field(default=None)

    error_name: str | None = Field(default=None)
    error_message: str | None = Field(default=None)
    error_context: dict | None = Field(
        default=None,
        sa_column=Column(JSONB, nullable=True),
    )

    sandbox_id: str | None = Field(default=None)
    llm_provider: str | None = Field(default=None)
    llm_model: str | None = Field(default=None)
    llm_base_url: str | None = Field(default=None)

    started_at: datetime | None = Field(
        default=None,
        sa_column=Column(TIMESTAMP(timezone=True), nullable=True),
    )
    completed_at: datetime | None = Field(
        default=None,
        sa_column=Column(TIMESTAMP(timezone=True), nullable=True),
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(
            TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")
        ),
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(
            TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")
        ),
    )


__all__ = ["Review", "ReviewState"]