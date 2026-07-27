from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import Column, text
from sqlalchemy.dialects.postgresql import TIMESTAMP
from sqlmodel import Field, ForeignKey, SQLModel

from app.models.enums import ReviewVerdict

if TYPE_CHECKING:
    pass


class ReviewSummary(SQLModel, table=True):
    id: UUID = Field(
        default_factory=uuid4,
        primary_key=True,
    )
    pr_id: str = Field(
        sa_column_args=(ForeignKey("pullrequest.id", ondelete="CASCADE"),),
        nullable=False,
    )
    commit_id: str = Field(nullable=False)
    github_review_id: str | None = Field(default=None, nullable=True)
    summary: str = Field(nullable=False)
    verdict: ReviewVerdict = Field(
        nullable=False,
    )

    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(
            TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")
        ),
    )
