"""``installations`` table.

One row per ``(user, github_installation, repo)`` the user has access
to via a GitHub App installation. Rows are upserted from the
``installation`` / ``installation_repositories`` webhook events with
``repo_id = NULL``; the ``repo_id`` is filled in when the user
indexes that specific repo (see :mod:`app.routers.ai`).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Optional

from sqlalchemy import Column, text
from sqlalchemy.dialects.postgresql import TIMESTAMP
from sqlmodel import Field, SQLModel

from app.utils.util import uuidToStr


class Installation(SQLModel, table=True):
    id: str = Field(
        default_factory=uuidToStr,
        primary_key=True,
    )
    user_id: str = Field(nullable=False, index=True)
    github_installation_id: int = Field(
        nullable=False,
        index=True,
        unique=True,
    )
    account_login: str = Field(max_length=255, nullable=False)
    account_type: str = Field(max_length=16, nullable=False)
    repository_selection: str = Field(max_length=16, nullable=False)
    suspended_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(TIMESTAMP(timezone=True), nullable=True),
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
