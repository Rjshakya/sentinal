"""AI routes: the setup-pipeline endpoints.

Two routes:

- ``POST /ai/repo/setup`` (asynchronous) — accepts a list of repos,
  dispatches a DBOS workflow per repo in parallel, and returns the
  workflow ids immediately (``202 Accepted``). The dashboard polls
  the GET endpoint for terminal state.
- ``GET /ai/repo/setup/{workflow_id}`` — returns the workflow's
  current status and the persisted :class:`SetupResult` if the
  workflow has reached a terminal state.

The router is a thin shell. All setup logic lives in
:mod:`app.services.agent.setup_workflow.workflow` and its step modules; the
router only handles request validation, idempotency, and the
DBOS dispatch / status read.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import cast

from dbos import DBOS, SetWorkflowID, WorkflowStatusString
from fastapi import APIRouter, HTTPException, Path, Request, status

from app.core.config import settings
from app.core.llm import LLMProviderStr
from app.schemas.setup import (
    SetupRequest,
    SetupStatusResponse,
    SetupWorkflowHandle,
    StartSetupResponse,
)
from app.services.agent.setup_workflow.types import SetupWorkflowInput
from app.services.agent.setup_workflow.workflow import setup_workflow

log = logging.getLogger(__name__)

router = APIRouter(prefix="/ai", tags=["ai"])


# --------------------------------------------------------------------------- #
# Workflow id                                                                  #
# --------------------------------------------------------------------------- #


def _workflow_id(*, user_id: str, github_repo_id: int) -> str:
    """Build the deterministic workflow id for one ``(user, repo)`` pair.

    Format: ``setup:{user_id}:{github_repo_id}``. The id is also the
    idempotency key — a second ``POST /ai/repo/setup`` for the same
    repo reuses the existing workflow if it is still running, or
    returns the cached status if it has already completed.
    """
    return f"setup:{user_id}:{github_repo_id}"


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
    to finish. Each repo gets its own DBOS workflow keyed on
    ``_workflow_id(user_id, github_repo_id)``; duplicate requests
    for the same repo reuse the running workflow.

    Idempotency rules (per repo):

    - ``PENDING`` / ``PROCESSING`` (any non-terminal) → return the
      existing workflow id.
    - ``SUCCESS`` → return the existing workflow id and its status
      (the client should poll for the cached result).
    - ``ERROR`` / ``MAX_RECOVERY_ATTEMPTS_EXCEEDED`` / ``CANCELLED``
      → start a fresh workflow so the user can retry.

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
    workflows: list[SetupWorkflowHandle] = []

    for r in payload.repos:
        wf_id = _workflow_id(user_id=user_id, github_repo_id=r.id)
        existing = await DBOS.get_workflow_status_async(wf_id)

        if existing is not None and existing.status in {
            WorkflowStatusString.PENDING,
            WorkflowStatusString.ENQUEUED,
            WorkflowStatusString.DELAYED,
            WorkflowStatusString.SUCCESS,
        }:
            continue

        # Either no existing workflow, or the prior one ended in
        # ERROR / CANCELLED / MAX_RECOVERY_ATTEMPTS_EXCEEDED — start
        # a fresh one. SetWorkflowID keeps the workflow id stable
        # across duplicate POSTs even when we want a fresh start.
        workflow_input = SetupWorkflowInput(
            user_id=user_id,
            github_repo_id=r.id,
            repo_owner=r.owner,
            repo_name=r.name,
            installation_id=r.installation_id,
            llm_provider=cast(LLMProviderStr, settings.llm_provider),
            llm_base_url=settings.llm_base_url or None,
            llm_api_key=settings.llm_api_key or settings.openai_api_key,
            llm_model=settings.llm_model,
        )
        with SetWorkflowID(wf_id):
            await DBOS.start_workflow_async(setup_workflow, workflow_input)
        workflows.append(
            SetupWorkflowHandle(
                github_repo_id=r.id,
                workflow_id=wf_id,
                status="PENDING",
            )
        )
        log.info(
            "ai.start_setup: dispatched workflow_id=%s user_id=%s github_repo_id=%s",
            wf_id,
            user_id,
            r.id,
        )

    return StartSetupResponse(workflows=workflows)


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
    :attr:`WorkflowStatus.error` and the cached
    :class:`SetupResult` (``ok=False``) is returned from the
    persisted DB row.

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
