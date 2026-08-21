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

    # Indexing mirror (DB columns added by migration ``98d1bc3c5752_``).
    # ``is_indexed`` is ``None`` until the first index run resolves it;
    # the boundary coerces ``None → False`` so the public contract is a
    # strict ``bool``. ``indexed_run_id`` is the last successful (or
    # failed) :class:`app.models.indexing.IndexRun` row's primary key;
    # it is server-side-only and is not exposed on the dashboard.
    is_indexed: Optional[bool] = Field(default=None, nullable=True)
    indexed_run_id: Optional[str] = Field(default=None, nullable=True)

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
