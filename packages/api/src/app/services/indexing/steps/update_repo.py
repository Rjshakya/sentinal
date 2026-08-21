"""DBOS steps that mirror the indexing workflow's terminal state onto
the ``repo`` table.

Two terminal states only — ``SUCCESS`` and ``ERROR`` — flip the
``is_indexed`` flag and ``indexed_run_id`` back-reference on the
matching :class:`app.models.repo.Repo` row so the repo list endpoint
and the frontend can show ``is_indexed = true | false`` without
needing to scan ``index_runs``.

Every step is best-effort: a DB blip or transient SQLAlchemy error is
logged and swallowed. The DBOS workflow's source of truth is its own
state table; the mirror is only a user-facing convenience.

The parent ``indexRepo`` workflow resolves the local :class:`Repo.id`
(UUID) once — after :func:`create_index_run_step` writes the
``IndexRun`` row — and passes the UUID to both mirror steps so the
step boundary is minimal.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from dbos import DBOS
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.db import async_session_maker
from app.models.repo import Repo

log = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(UTC)


async def _fetch_repo(session: AsyncSession, *, repo_id: str) -> Repo | None:
    return await session.get(Repo, repo_id)


@DBOS.step()
async def mark_repo_indexed_success_step(
    *,
    repo_id: str,
    run_id: str | None,
) -> None:
    """Flip the repo row to ``is_indexed = true``. Best-effort.

    Called from :func:`app.services.indexing.workflow.indexRepo` after
    the in-sandbox ingestion completes with a non-zero ``chunk_count``.
    ``indexed_run_id`` is back-pointed to the :class:`IndexRun` row
    that produced the dataset (no FK — same pattern as
    ``code_comments.github_comment_id``).
    """
    try:
        async with async_session_maker() as session:
            repo = await _fetch_repo(session, repo_id=repo_id)
            if repo is None:
                log.warning(
                    "mark_repo_indexed_success_step: repo_id=%s not found",
                    repo_id,
                )
                return
            repo.is_indexed = True
            repo.indexed_run_id = run_id
            repo.updated_at = _utcnow()
            await session.commit()
        log.info(
            "mark_repo_indexed_success_step: ok repo_id=%s run_id=%s",
            repo_id,
            run_id,
        )
    except Exception:
        log.warning(
            "mark_repo_indexed_success_step: failed repo_id=%s",
            repo_id,
            exc_info=True,
        )


@DBOS.step()
async def mark_repo_indexed_error_step(
    *,
    repo_id: str,
    run_id: str | None,
) -> None:
    """Flip the repo row to ``is_indexed = false``. Best-effort.

    Called from the ``except IndexingError`` block of
    :func:`app.services.indexing.workflow.indexRepo`. Keeps the
    ``indexed_run_id`` back-reference (the last failed attempt is
    useful for the dashboard's debugging surface area).
    """
    try:
        async with async_session_maker() as session:
            repo = await _fetch_repo(session, repo_id=repo_id)
            if repo is None:
                log.warning(
                    "mark_repo_indexed_error_step: repo_id=%s not found",
                    repo_id,
                )
                return
            repo.is_indexed = False
            repo.indexed_run_id = run_id
            repo.updated_at = _utcnow()
            await session.commit()
        log.info(
            "mark_repo_indexed_error_step: ok repo_id=%s run_id=%s",
            repo_id,
            run_id,
        )
    except Exception:
        log.warning(
            "mark_repo_indexed_error_step: failed repo_id=%s",
            repo_id,
            exc_info=True,
        )


__all__ = [
    "mark_repo_indexed_error_step",
    "mark_repo_indexed_success_step",
]
