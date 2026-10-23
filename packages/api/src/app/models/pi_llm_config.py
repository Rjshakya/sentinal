"""``llmconfig`` table (v3 pi model config).

Persistent per-user pi model configuration. One row per ``user_id`` —
a user has exactly one active pi config. Unlike the v2
``llm_configs`` table (:class:`app.models.llm_config.LLMConfigRecord`)
there is no ``base_url`` column: pi resolves the provider endpoint
itself from the provider id.

The ``api_key`` is stored as plain ``str``. A follow-up should add
at-rest encryption and redact the column from any log / OTLP log
attribute payloads.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import Column, text
from sqlalchemy.dialects.postgresql import TIMESTAMP
from sqlmodel import Field, SQLModel

from app.utils.util import uuidToStr


class LLMConfig(SQLModel, table=True):
    __tablename__ = "llmconfig"  # type: ignore[assignment]

    id: str = Field(default_factory=uuidToStr, primary_key=True)

    user_id: str = Field(nullable=False, unique=True, index=True)
    provider: str = Field(
        nullable=False,
    )
    model_id: str = Field(
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
