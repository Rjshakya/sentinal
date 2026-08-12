"""``index_runs`` table — durable record of every indexing workflow run.

One row per ``DBOS`` invocation of :func:`app.services.indexing.workflow.indexRepo`.
The row mirrors the workflow's lifecycle state so the dashboard can
poll for progress without depending on DBOS's own workflow state
table — and so the team has a structured audit trail of every index
operation (who triggered it, what repo, when, what S3 bucket the
dataset landed in, what error if it failed).

State machine: ``STARTING`` → ``RUNNING`` → (``SUCCESS`` | ``ERROR``).
``STARTING`` is the transient initial state — the row exists but the
workflow has not yet created its sandbox. ``RUNNING`` is set once the
sandbox exists. ``SUCCESS`` / ``ERROR`` are terminal.

Every state transition is best-effort: a failure to update the row
never breaks the workflow itself. The DBOS workflow's own state is
the source of truth for execution; this table is the user-facing
mirror.
"""

from __future__ import annotations

import enum
from datetime import UTC, datetime

from sqlalchemy import Column, String, text
from sqlalchemy.dialects.postgresql import TIMESTAMP
from sqlmodel import Field, SQLModel

from app.utils.util import uuidToStr


class IndexRunState(str, enum.Enum):
    """Lifecycle state of an :class:`IndexRun` row.

    Values are uppercase strings stored as a Postgres ENUM column;
    SQLModel maps ``str`` + :class:`enum.Enum` automatically.
    """

    STARTING = "STARTING"
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    ERROR = "ERROR"


class IndexRun(SQLModel, table=True):
    """One row per dispatched ``indexRepo`` workflow.

    The ``workflow_id`` column carries the deterministic DBOS id
    (``index:{owner}:{repo}``) and is unique — a duplicate dispatch
    reuses the same row via DBOS's workflow idempotency.
    """

    id: str = Field(
        default_factory=uuidToStr,
        primary_key=True,
    )
    user_id: str = Field(nullable=False, index=True)
    workflow_id: str = Field(nullable=False, unique=True, index=True)

    repo_owner: str = Field(nullable=False)
    repo_name: str = Field(nullable=False)
    repo_url: str = Field(nullable=False, max_length=1024)
    default_branch: str | None = Field(default=None)

    state: IndexRunState = Field(
        default=IndexRunState.STARTING,
        sa_column=Column(String(16), nullable=False, index=True),
    )

    chunk_count: int | None = Field(default=None)
    file_count: int | None = Field(default=None)
    error_name: str | None = Field(default=None)
    error_message: str | None = Field(default=None)
    sandbox_id: str | None = Field(default=None)
    s3_bucket: str | None = Field(default=None)

    started_at: datetime | None = Field(
        default=None,
        sa_column=Column(TIMESTAMP(timezone=True), nullable=True),
    )
    finished_at: datetime | None = Field(
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


__all__ = ["IndexRun", "IndexRunState"]
