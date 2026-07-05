from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import Column, text
from sqlalchemy.dialects.postgresql import TIMESTAMP
from sqlmodel import Field, SQLModel

from app.models.enums import PRStatus

if TYPE_CHECKING:
    pass


class PullRequest(SQLModel, table=True):
    id: str = Field(primary_key=True, nullable=False)
    repo_id: str = Field(foreign_key="repo.id", nullable=False)
    number: int = Field(nullable=False)
    author: str = Field(nullable=False)
    title: str = Field(nullable=False)
    body: str | None = Field(default=None)
    status: PRStatus = Field(default=PRStatus.OPEN, nullable=False)
    base_branch: str = Field(nullable=False)
    base_sha: str = Field(nullable=False)
    head_branch: str = Field(nullable=False)
    head_sha: str = Field(nullable=False)

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
