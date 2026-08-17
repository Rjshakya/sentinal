"""AI routes: the setup-pipeline endpoints.

Two routes:

- ``POST /ai/repo/setup`` (asynchronous) — accepts a list of repos,
  skips any that already have a row in the ``repos`` table, and
  dispatches a DBOS workflow for the rest. Returns the workflow ids
  (or skip markers) immediately (``202 Accepted``). The dashboard
  polls the GET endpoint for terminal state.
- ``GET /ai/repo/setup/{workflow_id}`` — returns the workflow's
  current status. On a terminal ``ERROR`` state the typed error name
  + message are surfaced through ``error_name`` / ``error_message``;
  no row is persisted beyond DBOS's own workflow state.

The router is a thin shell. All setup logic lives in
:mod:`app.services.setup.workflow` and its step modules; the
router only handles request validation, the Repo-row skip check,
and the DBOS dispatch / status read.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from dbos import DBOS, WorkflowStatusString
from fastapi import APIRouter, HTTPException, Path, Request, status
from sqlmodel import select

from app.core.config import settings
from app.core.db import async_session_maker
from app.models.repo import Repo
from app.schemas.setup import (
    SetupRequest,
    SetupStatusResponse,
    SetupWorkflowHandle,
    StartSetupResponse,
)
from app.services.setup.types import SetupWorkflowInput
from app.services.setup.workflow import setup_workflow

log = logging.getLogger(__name__)

router = APIRouter(prefix="/ai", tags=["ai"])


# --------------------------------------------------------------------------- #
# Workflow id                                                                  #
# --------------------------------------------------------------------------- #


def _parse_workflow_id(workflow_id: str) -> tuple[str, int] | None:
    """Parse ``setup:{user_id}:{github_repo_id}`` into ``(user_id, github_repo_id)``.

    Returns ``None`` on any malformed input. ``user_id`` is assumed
    not to contain ``:`` (WorkOS user ids do not).
    """
    parts = workflow_id.split(":")
    if len(parts) != 3 or parts[0] != "setup":
        return None
    try:
        return parts[1], int(parts[2])
    except ValueError:
        return None


# --------------------------------------------------------------------------- #
# POST /ai/repo/setup — async dispatch                                          #
# --------------------------------------------------------------------------- #


@router.post(
    "/repo/setup",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=StartSetupResponse,
)
async def start_setup_repos(
    payload: SetupRequest,
    request: Request,
) -> StartSetupResponse:
    """Dispatch a setup workflow per repo and return their ids.

    The handler is asynchronous — it does not wait for the agents
    to finish. Each repo in the request that does **not** already
    have a row in the ``repos`` table gets its own DBOS workflow;
    repos that do have a row are reported as ``skipped=True`` with
    ``workflow_id=None`` and the dashboard does not poll them.

    The check is keyed on ``github_repo_id`` alone (which is
    globally UNIQUE in the ``repos`` table), so a second POST for
    an already-set-up repo is always skipped regardless of which
    user triggers it.

    Note: there is no in-flight dedup. A rapid duplicate POST while
    a setup workflow is mid-run (before its first step commits the
    ``Repo`` row) will start a second workflow for the same repo.
    The workflow's own ``_upsert_repo`` is idempotent at the DB
    layer, so this is safe but wastes work.

    Preconditions:

    - The LLM must be configured (``LLM_BASE_URL``, ``LLM_MODEL`` and
      an API key). Otherwise we 503.
    - The active sandbox provider must be configured. The workflow
      will surface a 503-equivalent in the status response on the
      first attempt.
    """
    if not payload.repos:
        raise HTTPException(
            status_code=400,
            detail="`repos` must contain at least one item",
        )

    if not settings.llm_configured:
        raise HTTPException(
            status_code=503,
            detail=(
                "Setup LLM is not configured. Set LLM_BASE_URL, LLM_MODEL, "
                "and LLM_API_KEY (or OPENAI_API_KEY) in the environment."
            ),
        )

    user_id: str = request.state.user_id
    requested_ids = [r.id for r in payload.repos]
    existing_ids: set[int] = await _existing_repo_ids(requested_ids)
    workflows: list[SetupWorkflowHandle] = []

    for r in payload.repos:
        if r.id in existing_ids:
            workflows.append(
                SetupWorkflowHandle(
                    github_repo_id=r.id,
                    workflow_id=None,
                    status="PENDING",
                    skipped=True,
                )
            )
            log.info(
                "ai.start_setup: skipped github_repo_id=%s user_id=%s (Repo row exists)",
                r.id,
                user_id,
            )
            continue

        workflow_input = SetupWorkflowInput(
            user_id=user_id,
            github_repo_id=r.id,
            repo_owner=r.owner,
            repo_name=r.name,
            installation_id=r.installation_id,
            llm_config=settings.llm_config,
            default_branch=r.default_branch,
            index_after_setup=settings.indexing_configured,
        )

        workflow_info = await DBOS.start_workflow_async(setup_workflow, workflow_input)

        workflows.append(
            SetupWorkflowHandle(
                github_repo_id=r.id,
                workflow_id=workflow_info.workflow_id,
                status="PENDING",
                skipped=False,
            )
        )
        log.info(
            "ai.start_setup: dispatched workflow_id=%s user_id=%s github_repo_id=%s",
            workflow_info.workflow_id,
            user_id,
            r.id,
        )

    return StartSetupResponse(workflows=workflows)


async def _existing_repo_ids(github_repo_ids: list[int]) -> set[int]:
    """Return the subset of ``github_repo_ids`` that already have a ``Repo`` row.

    Single ``SELECT ... WHERE github_repo_id IN (...)``. Mirrors the
    bulk-lookup pattern in :mod:`app.routers.webhooks` (the
    ``installation_repositories.removed`` handler).
    """
    if not github_repo_ids:
        return set()
    async with async_session_maker() as session:
        stmt = select(Repo.github_repo_id).where(
            Repo.github_repo_id.in_(github_repo_ids)  # type: ignore[attr-defined]
        )
        result = await session.exec(stmt)
        return set(result.all())


# --------------------------------------------------------------------------- #
# GET /ai/repo/setup/{workflow_id} — status poll                               #
# --------------------------------------------------------------------------- #


@router.get(
    "/repo/setup/{workflow_id}",
    response_model=SetupStatusResponse,
)
async def get_setup_status(
    request: Request,
    workflow_id: str = Path(min_length=1),
) -> SetupStatusResponse:
    """Return the current status of a setup workflow.

    The handler reads DBOS's :func:`DBOS.get_workflow_status` (a sync
    call that does not wait for the workflow to finish). On a
    terminal ``SUCCESS`` state, the workflow's
    :class:`SetupWorkflowResult` is deserialized from
    :attr:`WorkflowStatus.output` and projected onto the response.
    On a terminal ``ERROR`` state, the exception is read from
    :attr:`WorkflowStatus.error` and its class name + message are
    projected onto ``error_name`` / ``error_message``.

    Auth: the workflow id encodes the user_id; the handler refuses
    cross-user reads with a 404 to avoid leaking workflow existence.
    """
    parsed = _parse_workflow_id(workflow_id)
    if parsed is None:
        raise HTTPException(
            status_code=400,
            detail="invalid workflow_id (expected 'setup:{user_id}:{github_repo_id}')",
        )
    owner_user_id, github_repo_id = parsed
    if owner_user_id != request.state.user_id:
        # Don't disclose existence to a different user.
        raise HTTPException(status_code=404, detail="workflow not found")

    dbos_status = DBOS.get_workflow_status(workflow_id)
    if dbos_status is None:
        raise HTTPException(status_code=404, detail="workflow not found")

    started_at = _epoch_ms_to_datetime(dbos_status.created_at)
    completed_at = _epoch_ms_to_datetime(dbos_status.updated_at)

    error_name: str | None = None
    error_message: str | None = None

    if dbos_status.status in {
        WorkflowStatusString.ERROR,
        WorkflowStatusString.MAX_RECOVERY_ATTEMPTS_EXCEEDED,
    }:
        if dbos_status.error is not None:
            error_name = type(dbos_status.error).__name__
            error_message = str(dbos_status.error)

    return SetupStatusResponse(
        workflow_id=workflow_id,
        status=dbos_status.status,
        github_repo_id=github_repo_id,
        error_name=error_name,
        error_message=error_message,
        started_at=started_at,
        completed_at=completed_at,
    )


def _epoch_ms_to_datetime(epoch_ms: int | None) -> datetime | None:
    """Convert a DBOS Unix-epoch-ms timestamp to a ``datetime``.

    Returns ``None`` when the input is ``None`` (DBOS leaves these
    fields unset for not-yet-started / not-yet-completed workflows).
    """
    if epoch_ms is None:
        return None
    return datetime.fromtimestamp(epoch_ms / 1000.0, tz=UTC)


__all__ = ["router"]
