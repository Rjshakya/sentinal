from datetime import UTC, datetime
from typing import TYPE_CHECKING, Optional
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, Column, ForeignKey, Index, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import TIMESTAMP
from sqlmodel import Field, Relationship, SQLModel

from app.models.enums import ReviewVerdict

if TYPE_CHECKING:
    from app.models.commit_snapshot import CommitSnapshot
    from app.models.pull_request import PullRequest


class ReviewSummary(SQLModel, table=True):
    __tablename__ = "review_summaries"
    __table_args__ = (
        CheckConstraint(
            "verdict IN ('APPROVE', 'COMMENT', 'REQUEST_CHANGES')",
            name="ck_review_summaries_verdict",
        ),
        UniqueConstraint("commit_id", name="uq_review_summaries_commit_id"),
        Index("ix_review_summaries_pr_id", "pr_id"),
    )

    id: UUID = Field(
        default_factory=uuid4,
        primary_key=True,
        sa_column_kwargs={"server_default": text("gen_random_uuid()")},
    )
    pr_id: UUID = Field(
        sa_column=Column(
            ForeignKey("pull_requests.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        )
    )
    commit_id: UUID = Field(
        sa_column=Column(
            ForeignKey("commit_snapshots.id", ondelete="CASCADE"),
            nullable=False,
        )
    )
    github_review_id: Optional[int] = Field(default=None, nullable=True)
    summary: str = Field(nullable=False)
    verdict: ReviewVerdict = Field(
        max_length=20,
        nullable=False,
    )

    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(
            TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")
        ),
    )

    pull_request: "PullRequest" = Relationship(back_populates="summaries")
    commit: "CommitSnapshot" = Relationship(back_populates="summary")
