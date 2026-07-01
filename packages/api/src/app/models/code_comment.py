from datetime import UTC, datetime
from typing import TYPE_CHECKING, Optional
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    Column,
    ForeignKey,
    Index,
    text,
)
from sqlalchemy.dialects.postgresql import TIMESTAMP
from sqlmodel import Field, Relationship, SQLModel

from app.models.enums import CommentSeverity, CommentSide, CommentState

if TYPE_CHECKING:
    from app.models.commit_snapshot import CommitSnapshot
    from app.models.pull_request import PullRequest


class CodeComment(SQLModel, table=True):
    __tablename__ = "code_comments"
    __table_args__ = (
        CheckConstraint(
            "severity IN ('P1_CRITICAL', 'P2_WARNING', 'P3_NITPICK')",
            name="ck_code_comments_severity",
        ),
        CheckConstraint(
            "side IN ('RIGHT', 'LEFT')", name="ck_code_comments_side"
        ),
        CheckConstraint(
            "state IN ('ACTIVE', 'OUTDATED', 'RESOLVED')",
            name="ck_code_comments_state",
        ),
        Index("ix_code_comments_pr_id", "pr_id"),
        Index("ix_code_comments_commit_id", "commit_id"),
        Index(
            "ix_code_comments_commit_file_state",
            "commit_id",
            "file_name",
            "state",
        ),
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
            index=True,
        )
    )
    github_comment_id: Optional[int] = Field(default=None, nullable=True)
    file_name: str = Field(max_length=1024, nullable=False)
    comment: str = Field(nullable=False)
    severity: CommentSeverity = Field(
        max_length=16,
        nullable=False,
    )
    from_line: int = Field(nullable=False)
    to_line: int = Field(nullable=False)
    side: CommentSide = Field(
        default=CommentSide.RIGHT,
        max_length=8,
        nullable=False,
        sa_column_kwargs={"server_default": CommentSide.RIGHT.value},
    )
    node_type: Optional[str] = Field(default=None, max_length=128, nullable=True)
    state: CommentState = Field(
        default=CommentState.ACTIVE,
        max_length=16,
        nullable=False,
        sa_column_kwargs={"server_default": CommentState.ACTIVE.value},
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

    pull_request: "PullRequest" = Relationship(back_populates="comments")
    commit: "CommitSnapshot" = Relationship(back_populates="comments")
