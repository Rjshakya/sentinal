from datetime import UTC, datetime
from typing import TYPE_CHECKING, Optional
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, Column, ForeignKey, Index, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import TIMESTAMP
from sqlmodel import Field, Relationship, SQLModel

from app.models.enums import PRStatus

if TYPE_CHECKING:
    from app.models.code_comment import CodeComment
    from app.models.commit_snapshot import CommitSnapshot
    from app.models.repo import Repo
    from app.models.review_summary import ReviewSummary


class PullRequest(SQLModel, table=True):
    __tablename__ = "pull_requests"
    __table_args__ = (
        CheckConstraint(
            "status IN ('OPEN', 'CLOSED', 'MERGED')", name="ck_pull_requests_status"
        ),
        UniqueConstraint("github_pr_id", name="uq_pull_requests_github_pr_id"),
        UniqueConstraint("repo_id", "number", name="uq_pull_requests_repo_id_number"),
        Index("ix_pull_requests_repo_id", "repo_id"),
        Index("ix_pull_requests_status", "status"),
    )

    id: UUID = Field(
        default_factory=uuid4,
        primary_key=True,
        sa_column_kwargs={"server_default": text("gen_random_uuid()")},
    )
    repo_id: UUID = Field(
        sa_column=Column(
            ForeignKey("repos.id", ondelete="CASCADE"), nullable=False, index=True
        )
    )
    github_pr_id: int = Field(nullable=False)
    number: int = Field(nullable=False)
    author: str = Field(max_length=255, nullable=False)
    title: str = Field(max_length=1024, nullable=False)
    body: Optional[str] = Field(default=None, sa_column_kwargs={"nullable": True})
    status: PRStatus = Field(
        default=PRStatus.OPEN,
        max_length=16,
        nullable=False,
        sa_column_kwargs={"server_default": PRStatus.OPEN.value},
    )
    base_branch: str = Field(max_length=255, nullable=False)
    base_sha: str = Field(max_length=64, nullable=False)
    head_branch: str = Field(max_length=255, nullable=False)
    head_sha: str = Field(max_length=64, nullable=False)

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

    repo: "Repo" = Relationship(back_populates="pull_requests")
    snapshots: list["CommitSnapshot"] = Relationship(
        back_populates="pull_request",
        cascade_delete=True,
        sa_relationship_kwargs={"passive_deletes": True},
    )
    comments: list["CodeComment"] = Relationship(
        back_populates="pull_request",
        cascade_delete=True,
        sa_relationship_kwargs={"passive_deletes": True},
    )
    summaries: list["ReviewSummary"] = Relationship(
        back_populates="pull_request",
        cascade_delete=True,
        sa_relationship_kwargs={"passive_deletes": True},
    )
