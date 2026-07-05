from datetime import UTC, datetime
from typing import Optional

from sqlalchemy import Column, text
from sqlalchemy.dialects.postgresql import TIMESTAMP
from sqlmodel import Field, ForeignKey, SQLModel

from app.models.enums import SandboxState
from app.utils.util import uuidToStr


class SandboxCreate(SQLModel):
    id: str
    user_id: str
    repo_id: str
    sandbox_name: str


class Sandbox(SQLModel, table=True):
    id: str = Field(
        default_factory=uuidToStr,
        primary_key=True,
    )
    user_id: str = Field(nullable=False)
    repo_id: str = Field(
        sa_column_args=(ForeignKey("repo.id", ondelete="CASCADE"),),
        nullable=False,
    )
    sandbox_name: str = Field(nullable=False)
    state: SandboxState = Field(default=SandboxState.STARTED, nullable=False)
    daytona_sandbox_id: str | None = Field(default=None, nullable=True)

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
    started_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(TIMESTAMP(timezone=True), nullable=True),
    )
    stopped_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(TIMESTAMP(timezone=True), nullable=True),
    )
