"""DBOS steps that mirror the indexing workflow's lifecycle onto the
``index_runs`` table.

Four steps — one per state transition:

- :func:`create_index_run_step` — inserts the ``STARTING`` row at
  workflow entry.
- :func:`mark_index_run_running_step` — flips it to ``RUNNING`` once
  the E2B sandbox is live.
- :func:`mark_index_run_success_step` — flips it to ``SUCCESS`` on a
  clean return.
- :func:`mark_index_run_error_step` — flips it to ``ERROR`` on a
  typed :class:`IndexingError`.

Every step is best-effort: a DB blip or transient SQLAlchemy error
never bubbles up to break the indexing workflow itself. The DBOS
workflow's own state is the source of truth for execution; this
table is the user-facing mirror that the dashboard polls.

The :func:`@DBOS.step` decorator (rather than
:func:`@dbos_datasource.transaction`) keeps the steps consistent with
the rest of the indexing pipeline — see
:func:`app.services.agent.setup_workflow.steps.ensure_repo_and_sandbox.ensure_repo_and_sandbox_step`
for the same pattern.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from dbos import DBOS
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import async_session_maker
from app.models.indexing import IndexRun, IndexRunState

log = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(UTC)


async def _fetch_run(session: AsyncSession, run_id: str) -> IndexRun | None:
    return await session.get(IndexRun, run_id)


@DBOS.step()
async def create_index_run_step(
    *,
    user_id: str,
    repo_owner: str,
    repo_name: str,
    repo_url: str,
    default_branch: str | None,
    s3_bucket: str | None,
) -> str | None:
    """Insert a ``STARTING`` row for the current workflow. Best-effort.

    Uses :data:`DBOS.workflow_id` as the deterministic DBOS id so the
    row can be looked up later via the same id the router returned.
    Returns the new row's ``id`` so the workflow can carry it across
    step boundaries; ``None`` on any failure (logged, never raised).
    """
    workflow_id = DBOS.workflow_id or ""
    try:
        async with async_session_maker() as session:
            run = IndexRun(
                user_id=user_id,
                workflow_id=workflow_id,
                repo_owner=repo_owner,
                repo_name=repo_name,
                repo_url=repo_url,
                default_branch=default_branch,
                state=IndexRunState.STARTING,
                s3_bucket=s3_bucket,
            )
            session.add(run)
            await session.commit()
            await session.refresh(run)
        log.info(
            "create_index_run_step: ok run_id=%s workflow_id=%s owner=%s repo=%s",
            run.id,
            workflow_id,
            repo_owner,
            repo_name,
        )
        return run.id
    except Exception:
        log.warning(
            "create_index_run_step: failed workflow_id=%s owner=%s repo=%s",
            workflow_id,
            repo_owner,
            repo_name,
            exc_info=True,
        )
        return None


@DBOS.step()
async def mark_index_run_running_step(
    *,
    run_id: str | None,
    sandbox_id: str,
) -> None:
    """Flip the row to ``RUNNING`` and record the E2B sandbox id. Best-effort."""
    if run_id is None:
        return
    try:
        async with async_session_maker() as session:
            run = await _fetch_run(session, run_id)
            if run is None:
                log.warning("mark_index_run_running_step: run_id=%s not found", run_id)
                return
            run.state = IndexRunState.RUNNING
            run.sandbox_id = sandbox_id
            run.started_at = _utcnow()
            run.updated_at = _utcnow()
            await session.commit()
        log.info(
            "mark_index_run_running_step: ok run_id=%s sandbox_id=%s",
            run_id,
            sandbox_id,
        )
    except Exception:
        log.warning(
            "mark_index_run_running_step: failed run_id=%s", run_id, exc_info=True
        )


@DBOS.step()
async def mark_index_run_success_step(
    *,
    run_id: str | None,
    chunk_count: int,
    file_count: int,
) -> None:
    """Flip the row to ``SUCCESS`` and persist chunk/file counts. Best-effort."""
    if run_id is None:
        return
    try:
        async with async_session_maker() as session:
            run = await _fetch_run(session, run_id)
            if run is None:
                log.warning("mark_index_run_success_step: run_id=%s not found", run_id)
                return
            run.state = IndexRunState.SUCCESS
            run.chunk_count = chunk_count
            run.file_count = file_count
            run.finished_at = _utcnow()
            run.updated_at = _utcnow()
            await session.commit()
        log.info(
            "mark_index_run_success_step: ok run_id=%s chunks=%d files=%d",
            run_id,
            chunk_count,
            file_count,
        )
    except Exception:
        log.warning(
            "mark_index_run_success_step: failed run_id=%s", run_id, exc_info=True
        )


@DBOS.step()
async def mark_index_run_error_step(
    *,
    run_id: str | None,
    error_name: str,
    error_message: str,
) -> None:
    """Flip the row to ``ERROR`` and persist the typed error info. Best-effort."""
    if run_id is None:
        return
    try:
        async with async_session_maker() as session:
            run = await _fetch_run(session, run_id)
            if run is None:
                log.warning("mark_index_run_error_step: run_id=%s not found", run_id)
                return
            run.state = IndexRunState.ERROR
            run.error_name = error_name
            run.error_message = error_message
            run.finished_at = _utcnow()
            run.updated_at = _utcnow()
            await session.commit()
        log.info(
            "mark_index_run_error_step: ok run_id=%s error=%s",
            run_id,
            error_name,
        )
    except Exception:
        log.warning(
            "mark_index_run_error_step: failed run_id=%s", run_id, exc_info=True
        )


__all__ = [
    "create_index_run_step",
    "mark_index_run_error_step",
    "mark_index_run_running_step",
    "mark_index_run_success_step",
]
