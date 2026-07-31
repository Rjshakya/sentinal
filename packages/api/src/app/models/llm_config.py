"""``llm_configs`` table.

Persistent per-user LLM configuration. One row per
``(user_id, provider, model_id, base_url)`` so a user can register
multiple configs (one per provider / model / endpoint) and pick the
active one at request time.

The ``api_key`` is stored as plain ``str`` to mirror the existing
Pydantic :class:`app.core.llm.LLMConfig.api_key` convention. A
follow-up should add at-rest encryption and redact the column from
any log / Sentry / structured_log payloads.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import Column, text
from sqlalchemy.dialects.postgresql import TIMESTAMP
from sqlmodel import Field, SQLModel

from app.utils.util import uuidToStr


class LLMConfigRecord(SQLModel, table=True):
    id: str = Field(default_factory=uuidToStr, primary_key=True)

    user_id: str = Field(nullable=False, index=True)
    provider: str = Field(
        nullable=False,
    )
    model_id: str = Field(
        nullable=False,
    )
    base_url: str = Field(
        nullable=False,
    )
    api_key: str = Field(
        nullable=False,
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
