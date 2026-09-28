from datetime import UTC, datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Column, text
from sqlalchemy.dialects.postgresql import TIMESTAMP
from sqlmodel import Field, SQLModel

if TYPE_CHECKING:
    pass


class Repo(SQLModel, table=True):
    id: str = Field(
        nullable=False,
        primary_key=True,
    )
    user_id: str = Field(nullable=False, index=True)
    org_id: Optional[str] = Field(
        default=None,
    )
    github_repo_id: int = Field(nullable=False, unique=True)
    repo_name: str = Field(nullable=False)
    repo_owner: str = Field(nullable=False)
    clone_url: str = Field(max_length=1024, nullable=False)
    url: Optional[str] = Field(default=None, nullable=True)
    private: bool = Field(default=False, nullable=False)
    default_branch: str | None = Field(default=None, nullable=True)

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
