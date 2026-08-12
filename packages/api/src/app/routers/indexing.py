"""Indexing-pipeline routes.

Three endpoints, all protected by :class:`AuthMiddleware`:

- ``POST /api/indexing/repo`` — dispatch :func:`indexRepo` for a repo
  URL. Returns ``202 Accepted`` with the deterministic workflow id
  and the initial ``STARTING`` state. Requires the repo to be in the
  user's installed repos (joined via the ``repos`` table); ``404`` if
  not installed.
- ``GET /api/indexing/{workflow_id}`` — return the matching
  :class:`IndexRun` row (state, counts, error, timestamps). ``404``
  on cross-user reads.
- ``GET /api/indexing`` — list the user's runs, paginated, newest
  first.

The router is a thin shell. All real logic lives in
:mod:`app.services.indexing.workflow` (DBOS) and
:mod:`app.services.indexing.steps.index_run_steps` (state mirror).
"""

from __future__ import annotations

import logging

from dbos import DBOS, SetWorkflowID
from fastapi import APIRouter, HTTPException, Path, Query, Request, status
from sqlalchemy import func
from sqlmodel import select

from app.core.db import async_session_maker
from app.models.indexing import IndexRun
from app.models.repo import Repo
from app.repositories.base import Repository
from app.schemas.indexing import (
    IndexRunListResponse,
    IndexRunOut,
    IndexRunTriggerIn,
    IndexRunTriggerOut,
    to_index_run_out,
)
from app.services.indexing.helpers import (
    index_workflow_id,
    parse_repo_url,
)
from app.services.indexing.types import IndexWorkflowInput
from app.services.indexing.workflow import indexRepo

log = logging.getLogger(__name__)

router = APIRouter(prefix="/indexing", tags=["indexing"])


# --------------------------------------------------------------------------- #
# Helpers                                                                      #
# --------------------------------------------------------------------------- #


async def _is_repo_installed(*, user_id: str, owner: str, repo: str) -> bool:
    """Return ``True`` when the user has a row in ``repos`` for ``owner/repo``.

    Rows in the ``repos`` table are populated by the GitHub
    ``installation_repositories`` webhook events, so this is the
    canonical "is this repo installed for this user" check. A
    non-installed repo makes the POST ineligible (404) — once private
    indexing lands, this same gate becomes the authorisation check
    for cloning.
    """
    async with async_session_maker() as session:
        repo_row = await Repository(Repo, session).find_by_fields(
            user_id=user_id,
            repo_owner=owner,
            repo_name=repo,
        )
        return repo_row is not None


async def _list_user_runs(
    *,
    user_id: str,
    limit: int,
    offset: int,
) -> tuple[list[IndexRun], int]:
    """Return one page of the user's runs (newest first) and the total count.

    Bypasses the generic :class:`Repository` because the list endpoint
    needs both pagination and ordering, neither of which the generic
    base supports out of the box. Issues two queries: one paginated
    ``SELECT`` and one ``SELECT COUNT(*)``.
    """
    async with async_session_maker() as session:
        items_stmt = (
            select(IndexRun)
            .where(IndexRun.user_id == user_id)
            .order_by(IndexRun.created_at.desc())  # type: ignore[attr-defined]
            .limit(limit)
            .offset(offset)
        )
        items = list((await session.exec(items_stmt)).all())

        count_stmt = (
            select(func.count())
            .select_from(IndexRun)
            .where(IndexRun.user_id == user_id)
        )
        total = int((await session.exec(count_stmt)).one())

    return items, total


# --------------------------------------------------------------------------- #
# POST /api/indexing/repo                                                      #
# --------------------------------------------------------------------------- #


@router.post(
    "/repo",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=IndexRunTriggerOut,
)
async def trigger_index_run(
    body: IndexRunTriggerIn,
    request: Request,
) -> IndexRunTriggerOut:
    """Dispatch :func:`indexRepo` for ``body.repo_url``.

    Verifies the repo is installed for the calling user. The dispatch
    uses the deterministic workflow id
    :func:`app.services.indexing.helpers.index_workflow_id`, so a
    second POST for the same ``owner/repo`` reuses the in-flight
    workflow (or returns its cached result if it has already
    completed).
    """
    try:
        owner, repo_name = parse_repo_url(body.repo_url)
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail=f"invalid repo_url: {exc}",
        ) from exc

    user_id: str = request.state.user_id

    if not await _is_repo_installed(user_id=user_id, owner=owner, repo=repo_name):
        raise HTTPException(
            status_code=404,
            detail="repo is not installed for this user",
        )

    workflow_id = index_workflow_id(owner, repo_name)
    with SetWorkflowID(workflow_id):
        await DBOS.start_workflow_async(
            indexRepo,
            IndexWorkflowInput(
                user_id=user_id,
                repo_url=body.repo_url,
                default_branch=body.default_branch,
            ),
        )

    log.info(
        "indexing.trigger: dispatched workflow_id=%s user_id=%s owner=%s repo=%s",
        workflow_id,
        user_id,
        owner,
        repo_name,
    )

    return IndexRunTriggerOut(workflow_id=workflow_id)


# --------------------------------------------------------------------------- #
# GET /api/indexing/{workflow_id}                                              #
# --------------------------------------------------------------------------- #


@router.get(
    "/{workflow_id}",
    response_model=IndexRunOut,
)
async def get_index_run(
    request: Request,
    workflow_id: str = Path(min_length=1),
) -> IndexRunOut:
    """Return the :class:`IndexRun` row for the given workflow id.

    Cross-user reads return ``404`` (never ``403``) so the endpoint
    does not disclose the existence of another user's workflow.
    """
    user_id: str = request.state.user_id
    async with async_session_maker() as session:
        repo = Repository(IndexRun, session)
        run = await repo.find_by_fields(workflow_id=workflow_id, user_id=user_id)
    if run is None:
        raise HTTPException(status_code=404, detail="index run not found")
    return to_index_run_out(run)


# --------------------------------------------------------------------------- #
# GET /api/indexing                                                            #
# --------------------------------------------------------------------------- #


@router.get(
    "/",
    response_model=IndexRunListResponse,
)
async def list_index_runs(
    request: Request,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> IndexRunListResponse:
    """List the user's runs, newest first, paginated.

    ``limit`` defaults to 20 and is capped at 100 to keep the response
    bounded; ``offset`` is the zero-based row offset.
    """
    user_id: str = request.state.user_id
    items, total = await _list_user_runs(user_id=user_id, limit=limit, offset=offset)
    return IndexRunListResponse(
        items=[to_index_run_out(row) for row in items],
        total=total,
        limit=limit,
        offset=offset,
    )


__all__ = [
    "_is_repo_installed",
    "_list_user_runs",
    "get_index_run",
    "list_index_runs",
    "router",
    "trigger_index_run",
]
