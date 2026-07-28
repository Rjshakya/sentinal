"""HTTP schemas for the setup pipeline.

The endpoint is **asynchronous** — ``POST /ai/repo/setup`` dispatches
a DBOS workflow per repo and returns the workflow ids immediately
(``202 Accepted``). The client polls the new ``GET /ai/repo/setup/{id}``
endpoint for the terminal status and the persisted :class:`SetupResult`.

The schemas here are the HTTP-shape contract only; the workflow
itself lives in :mod:`app.services.agent.setup.workflow`.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field

WorkflowStatus = Literal[
    "PENDING",
    "SUCCESS",
    "ERROR",
    "MAX_RECOVERY_ATTEMPTS_EXCEEDED",
    "CANCELLED",
    "ENQUEUED",
    "DELAYED",
]
"""Subset of DBOS :class:`dbos.WorkflowStatusString` exposed to clients.

The dashboard only ever sees ``PENDING`` (workflow is still running)
and the two terminal states (``SUCCESS`` and ``ERROR``). The other
values are reserved for the API status endpoint and the DBOS
admin server.
"""


# --------------------------------------------------------------------------- #
# Request                                                                      #
# --------------------------------------------------------------------------- #


class SetupRepo(BaseModel):
    """A single repo to set up.

    ``id`` is the GitHub repo id (numeric, coerced to int in the
    handler). ``owner`` and ``name`` are needed to construct the
    authenticated clone URL inside the sandbox. ``installation_id`` is
    the local :class:`app.models.installation.Installation` row's
    primary key, used to look up the GitHub installation id and mint
    a fresh install token for the clone.
    """

    id: int = Field(
        description="GitHub repo id (numeric).",
    )
    owner: str = Field(
        description="GitHub repo owner (org or user).",
    )
    name: str = Field(
        description="GitHub repo name.",
    )
    installation_id: str = Field(
        description="Local Installation.id (UUID) used to mint the "
        "install token for the clone.",
    )


class SetupRequest(BaseModel):
    """Body of ``POST /ai/repo/setup``."""

    repos: list[SetupRepo] = Field(
        min_length=1,
        description="Non-empty list of repos to set up. The handler "
        "validates the request and 400s on an empty list.",
    )


# --------------------------------------------------------------------------- #
# POST response — 202 Accepted                                                  #
# --------------------------------------------------------------------------- #


class SetupWorkflowHandle(BaseModel):
    """One entry in :class:`StartSetupResponse.workflows`.

    Returned by the POST handler. The dashboard stores these and
    polls :class:`SetupStatusResponse` for each ``workflow_id`` until
    it sees a terminal state. Entries with ``skipped=True`` have
    ``workflow_id=None`` and must not be polled — the corresponding
    repo already has a row in the ``repos`` table.
    """

    github_repo_id: int = Field(
        description="GitHub repo id, echoed back from the request.",
    )
    workflow_id: Optional[str] = Field(
        default=None,
        description=(
            "DBOS workflow id; the dashboard uses this as the poll "
            "key. ``None`` when ``skipped=True``."
        ),
    )
    status: WorkflowStatus = Field(
        description="Initial workflow status. Always 'PENDING' for "
        "freshly-started workflows and for skipped entries.",
    )
    skipped: bool = Field(
        default=False,
        description=(
            "True when the repo was skipped because a row already "
            "exists in the ``repos`` table for this "
            "``github_repo_id``. In that case ``workflow_id`` is "
            "``None`` and the dashboard should not poll the status "
            "endpoint."
        ),
    )


class StartSetupResponse(BaseModel):
    """Body of the ``POST /ai/repo/setup`` response.

    Status code is ``202 Accepted``; one :class:`SetupWorkflowHandle`
    per repo in the request, in the same order.
    """

    workflows: list[SetupWorkflowHandle]


# --------------------------------------------------------------------------- #
# GET response — status poll                                                   #
# --------------------------------------------------------------------------- #


class SetupStatusResponse(BaseModel):
    """Body of ``GET /ai/repo/setup/{workflow_id}``.

    Returned by the status endpoint. ``setup`` is ``None`` while the
    workflow is still running (no row has been persisted yet);
    ``error`` is ``None`` on success. Both fields are populated for
    terminal ``SUCCESS`` and ``ERROR`` states.
    """

    workflow_id: str = Field(
        description="DBOS workflow id.",
    )
    status: WorkflowStatus = Field(
        description="Current workflow status.",
    )
    github_repo_id: Optional[int] = Field(
        default=None,
        description="GitHub repo id; extracted from the workflow id "
        "('setup:{user_id}:{github_repo_id}').",
    )

    error_name: Optional[str] = Field(
        default=None,
        description="Class name of the typed SetupError that the "
        "workflow caught, when status is ERROR.",
    )
    error_message: Optional[str] = Field(
        default=None,
        description="Human-readable error message; the same string "
        "embedded in setup.notes when status is ERROR.",
    )
    started_at: Optional[datetime] = Field(
        default=None,
        description="Wall-clock start time reported by DBOS.",
    )
    completed_at: Optional[datetime] = Field(
        default=None,
        description="Wall-clock completion time; null while pending.",
    )


__all__ = [
    "SetupRepo",
    "SetupRequest",
    "SetupStatusResponse",
    "SetupWorkflowHandle",
    "StartSetupResponse",
    "WorkflowStatus",
]
