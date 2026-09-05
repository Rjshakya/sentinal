from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Column,
    text,
)
from sqlalchemy.dialects.postgresql import TIMESTAMP
from sqlmodel import Field, ForeignKey, SQLModel

from app.models.enums import CommentSeverity, CommentSide, CommentState
from app.utils.util import uuidToStr

if TYPE_CHECKING:
    pass


class CodeComment(SQLModel, table=True):
    id: str = Field(default_factory=uuidToStr, primary_key=True)
    pr_id: str = Field(
        sa_column_args=(ForeignKey("pullrequest.id", ondelete="CASCADE"),),
        nullable=False,
    )
    review_id: str | None = Field(
        default=None,
        sa_column_args=(ForeignKey("review.id", ondelete="CASCADE"),),
        nullable=True,
        index=True,
    )
    commit_id: str = Field(nullable=False)
    github_comment_id: str | None = Field(default=None, nullable=True)
    github_review_id: str | None = Field(default=None, nullable=True)
    file_name: str = Field(nullable=False)
    comment: str = Field(nullable=False)
    severity: CommentSeverity = Field(nullable=False)
    from_line: int = Field(nullable=False)
    to_line: int = Field(nullable=False)
    side: CommentSide = Field(default=CommentSide.RIGHT, nullable=False)
    node_type: str | None = Field(default=None, nullable=True)
    state: CommentState = Field(default=CommentState.ACTIVE, nullable=False)

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
