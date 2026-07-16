"""``reposetupresult`` table.

One row per repo — the latest setup attempt supersedes the previous
one. The row carries the full :class:`app.services.agent.models.SetupResult`
payload plus the pipeline metadata (``llm_provider`` / ``llm_model`` /
``sandbox_id``) and a typed ``error_code`` for failure-mode filtering.

Enums are stored as ``VARCHAR`` in PG and as Python enums in our
codebase; no native PG enum types are used.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Optional

import sqlalchemy as sa
from sqlalchemy import Column, text
from sqlalchemy.dialects.postgresql import ARRAY, TIMESTAMP
from sqlmodel import Field, ForeignKey, SQLModel

from app.models.enums import SetupErrorCode, SetupRunStatus
from app.utils.util import uuidToStr


class RepoSetupResult(SQLModel, table=True):
    id: str = Field(default_factory=uuidToStr, primary_key=True)
    repo_id: str = Field(
        sa_column_args=(ForeignKey("repo.id", ondelete="CASCADE"),),
        nullable=False,
    )
    user_id: str = Field(nullable=False, index=True)

    status: SetupRunStatus = Field(
        sa_column=Column(sa.String(length=16), nullable=False),
    )
    ok: bool = Field(nullable=False)
    ecosystem: str = Field(
        sa_column=Column(sa.String(length=16), nullable=False),
    )
    manager: Optional[str] = Field(default=None, max_length=128)
    install_cmd: Optional[str] = Field(default=None, max_length=1024)
    duration_s: float = Field(nullable=False)
    notes: str = Field(
        sa_column=Column(sa.Text, nullable=False),
    )
    bootstrapped_tools: list[str] = Field(
        sa_column=Column(
            ARRAY(sa.String),
            nullable=False,
            server_default=text("'{}'::text[]"),
        ),
    )

    error_code: Optional[SetupErrorCode] = Field(
        default=None,
        sa_column=Column(sa.String(length=64), nullable=True),
    )
    error_message: Optional[str] = Field(
        default=None,
        sa_column=Column(sa.Text, nullable=True),
    )

    llm_provider: Optional[str] = Field(default=None, max_length=32)
    llm_model: Optional[str] = Field(default=None, max_length=128)
    sandbox_id: Optional[str] = Field(default=None, max_length=128)

    started_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(TIMESTAMP(timezone=True), nullable=False),
    )
    completed_at: Optional[datetime] = Field(
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
