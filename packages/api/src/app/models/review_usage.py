"""``review_usage`` table.

One row per review run, recording the aggregated token usage for the
PR. The row is written on both the success path
(``review_status=SUCCESS``, ``review_summary_id=<persisted summary>``)
and the failure path (``review_status=FAILED``,
``review_summary_id=None``).

The ``input_token_details`` JSONB column carries the cache_read /
cache_creation breakdown (``{"cache_read": int | None,
"cache_creation": int | None}``) as reported by the provider; it is
optional because not every provider surfaces cache metadata.

The ``llm_model_id`` / ``llm_provider`` / ``llm_base_url`` columns
snapshot the resolved :class:`app.core.llm.LLMConfig` at run time so
per-model cost and quality analytics never depend on a config row
that may later be edited or deleted. All three are nullable.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Optional
from uuid import UUID

from sqlalchemy import Column, text
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP
from sqlmodel import Field, ForeignKey, SQLModel

from app.models.enums import ReviewRunStatus
from app.utils.util import uuidToStr


class ReviewUsage(SQLModel, table=True):
    id: str = Field(default_factory=uuidToStr, primary_key=True)

    user_id: str = Field(nullable=False, index=True)
    pr_id: str = Field(
        sa_column_args=(ForeignKey("pullrequest.id", ondelete="CASCADE"),),
        nullable=False,
    )
    pr_number: int = Field(nullable=False)
    repo_id: str = Field(
        sa_column_args=(ForeignKey("repo.id", ondelete="CASCADE"),),
        nullable=False,
    )
    review_summary_id: Optional[UUID] = Field(
        default=None,
        sa_column_args=(ForeignKey("reviewsummary.id", ondelete="CASCADE"),),
        nullable=True,
    )

    review_status: ReviewRunStatus = Field(
        default=ReviewRunStatus.SUCCESS,
        nullable=False,
    )
    input_tokens: int = Field(nullable=False, default=0)
    output_tokens: int = Field(nullable=False, default=0)
    total_tokens: int = Field(nullable=False, default=0)
    input_token_details: Optional[dict] = Field(
        default=None,
        sa_column=Column(JSONB, nullable=True),
    )

    llm_model_id: Optional[str] = Field(default=None, nullable=True)
    llm_provider: Optional[str] = Field(default=None, nullable=True)
    llm_base_url: Optional[str] = Field(default=None, nullable=True)

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
