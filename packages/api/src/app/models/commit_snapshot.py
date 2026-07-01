from datetime import UTC, datetime
from typing import TYPE_CHECKING, Optional
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    Column,
    ForeignKey,
    Index,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import TIMESTAMP
from sqlmodel import Field, Relationship, SQLModel

from app.models.enums import AnalysisStatus

if TYPE_CHECKING:
    from app.models.code_comment import CodeComment
    from app.models.pull_request import PullRequest
    from app.models.review_summary import ReviewSummary


class CommitSnapshot(SQLModel, table=True):
    __tablename__ = "commit_snapshots"
    __table_args__ = (
        CheckConstraint(
            "analysis_status IN ('PENDING', 'PROCESSING', 'COMPLETED', 'FAILED')",
            name="ck_commit_snapshots_analysis_status",
        ),
        UniqueConstraint("pr_id", "sha", name="uq_commit_snapshots_pr_id_sha"),
        Index("ix_commit_snapshots_pr_id", "pr_id"),
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
    sha: str = Field(max_length=64, nullable=False)
    previous_reviewed_sha: Optional[str] = Field(
        default=None, max_length=64, nullable=True
    )
    analysis_status: AnalysisStatus = Field(
        default=AnalysisStatus.PENDING,
        max_length=16,
        nullable=False,
        sa_column_kwargs={"server_default": AnalysisStatus.PENDING.value},
    )
    error_message: Optional[str] = Field(default=None, nullable=True)

    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(
            TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")
        ),
    )

    pull_request: "PullRequest" = Relationship(back_populates="snapshots")
    comments: list["CodeComment"] = Relationship(
        back_populates="commit",
        cascade_delete=True,
        sa_relationship_kwargs={"passive_deletes": True},
    )
    summary: Optional["ReviewSummary"] = Relationship(
        back_populates="commit",
        cascade_delete=True,
        sa_relationship_kwargs={"passive_deletes": True},
    )
