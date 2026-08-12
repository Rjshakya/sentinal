"""HTTP schemas for the indexing pipeline.

Three endpoints (see :mod:`app.routers.indexing`):

- ``POST /api/indexing/repo`` — dispatch :func:`indexRepo`. Returns
  ``202 Accepted`` with the deterministic workflow id and the initial
  ``STARTING`` state. The dashboard polls :class:`IndexRunOut` for
  progress.
- ``GET /api/indexing/{workflow_id}`` — return the matching
  :class:`IndexRun` row. ``404`` on cross-user reads.
- ``GET /api/indexing`` — list the user's runs, paginated.

The schemas here are the HTTP-shape contract only; the workflow lives
in :mod:`app.services.indexing.workflow` and the state-machine mirror
lives in :mod:`app.services.indexing.steps.index_run_steps`.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

from app.models.indexing import IndexRun, IndexRunState


# --------------------------------------------------------------------------- #
# Request — POST /api/indexing/repo                                            #
# --------------------------------------------------------------------------- #


class IndexRunTriggerIn(BaseModel):
    """Body of ``POST /api/indexing/repo``.

    ``repo_url`` is the only required field; ``default_branch`` is
    optional and falls back to the remote default. ``user_id`` is
    never accepted on the wire — the router reads it from the
    sealed session cookie via ``AuthMiddleware``.
    """

    repo_url: str = Field(
        min_length=1,
        max_length=1024,
        description=(
            "Cloneable repo URL: ``https://github.com/owner/repo``, "
            "``git@github.com:owner/repo.git``, or bare ``owner/repo``."
        ),
    )
    default_branch: Optional[str] = Field(
        default=None,
        max_length=255,
        description=(
            "Branch to check out; when ``None`` the remote default "
            "is used."
        ),
    )


# --------------------------------------------------------------------------- #
# Response — POST 202 Accepted                                                  #
# --------------------------------------------------------------------------- #


class IndexRunTriggerOut(BaseModel):
    """Body of the ``POST /api/indexing/repo`` response.

    Status code is ``202 Accepted``. The dashboard stores the
    ``workflow_id`` and polls :class:`IndexRunOut` until a terminal
    state is observed.
    """

    workflow_id: str = Field(
        description=(
            "DBOS workflow id (``index:{owner}:{repo}``). Deterministic; "
            "a second POST for the same repo reuses the same id."
        ),
    )
    state: IndexRunState = Field(
        default=IndexRunState.STARTING,
        description=(
            "Initial state. Always ``STARTING`` on a freshly dispatched "
            "workflow; the dashboard should not interpret this as the "
            "final state."
        ),
    )


# --------------------------------------------------------------------------- #
# Response — GET single                                                        #
# --------------------------------------------------------------------------- #


class IndexRunOut(BaseModel):
    """Body of the ``GET /api/indexing/{workflow_id}`` response.

    Mirrors the :class:`app.models.indexing.IndexRun` row with every
    field exposed. ``error_name`` / ``error_message`` are populated
    only when ``state == ERROR``; chunk + file counts are populated
    only when ``state == SUCCESS``.
    """

    id: str = Field(description="Local UUID primary key.")
    workflow_id: str = Field(description="DBOS workflow id.")
    state: IndexRunState
    repo_owner: str
    repo_name: str
    repo_url: str
    default_branch: Optional[str] = None
    chunk_count: Optional[int] = None
    file_count: Optional[int] = None
    error_name: Optional[str] = None
    error_message: Optional[str] = None
    sandbox_id: Optional[str] = None
    s3_bucket: Optional[str] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime


def to_index_run_out(row: IndexRun) -> IndexRunOut:
    """Project an :class:`IndexRun` ORM row to its public response.

    Centralised here so the router is free of model-to-schema mapping
    noise and so any future field addition is a one-line change.
    """
    return IndexRunOut(
        id=row.id,
        workflow_id=row.workflow_id,
        state=row.state,
        repo_owner=row.repo_owner,
        repo_name=row.repo_name,
        repo_url=row.repo_url,
        default_branch=row.default_branch,
        chunk_count=row.chunk_count,
        file_count=row.file_count,
        error_name=row.error_name,
        error_message=row.error_message,
        sandbox_id=row.sandbox_id,
        s3_bucket=row.s3_bucket,
        started_at=row.started_at,
        finished_at=row.finished_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


# --------------------------------------------------------------------------- #
# Response — GET list                                                          #
# --------------------------------------------------------------------------- #


class IndexRunListResponse(BaseModel):
    """Body of the ``GET /api/indexing`` response.

    Ordered by ``created_at`` descending. ``total`` is the unfiltered
    row count for the user, so the dashboard can render pagination
    controls without a second request.
    """

    items: list[IndexRunOut] = Field(
        description="Page of index runs, newest first.",
    )
    total: int = Field(
        description="Total number of runs for this user (unfiltered).",
    )
    limit: int = Field(
        description="Page size that was applied.",
    )
    offset: int = Field(
        description="Offset that was applied.",
    )


__all__ = [
    "IndexRunListResponse",
    "IndexRunOut",
    "IndexRunTriggerIn",
    "IndexRunTriggerOut",
    "to_index_run_out",
]
