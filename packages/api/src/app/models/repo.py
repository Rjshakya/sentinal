from datetime import UTC, datetime
from typing import TYPE_CHECKING, Optional
from uuid import UUID, uuid4

from sqlalchemy import Column, Index, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import TIMESTAMP
from sqlmodel import Field, Relationship, SQLModel

if TYPE_CHECKING:
    from app.models.pull_request import PullRequest


class Repo(SQLModel, table=True):
    __tablename__ = "repos"
    __table_args__ = (
        UniqueConstraint("github_repo_id", name="uq_repos_github_repo_id"),
        UniqueConstraint("repo_owner", "repo_name", name="uq_repos_owner_name"),
        Index("ix_repos_user_id", "user_id"),
        Index("ix_repos_org_id", "org_id"),
    )

    id: UUID = Field(
        default_factory=uuid4,
        primary_key=True,
        sa_column_kwargs={"server_default": text("gen_random_uuid()")},
    )
    user_id: str = Field(max_length=128, nullable=False)
    org_id: Optional[str] = Field(default=None, max_length=128)
    github_repo_id: int = Field(nullable=False)
    repo_name: str = Field(max_length=255, nullable=False)
    repo_owner: str = Field(max_length=255, nullable=False)
    clone_url: str = Field(max_length=1024, nullable=False)
    github_installation_id: int = Field(nullable=False)

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

    pull_requests: list["PullRequest"] = Relationship(
        back_populates="repo",
        cascade_delete=True,
        sa_relationship_kwargs={"passive_deletes": True},
    )
