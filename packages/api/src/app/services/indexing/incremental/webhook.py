"""GitHub ``push`` webhook adapter for the incremental indexing workflow.

Dispatches a verified default-branch push delivery to the DBOS
incremental workflow. Mirrors the ring structure of
:mod:`app.workflows.review.triggers`:

- **Ring 1 (pure)**       — :func:`push_skip_reason`,
  :func:`extract_push_files`, :func:`incremental_workflow_id`. No I/O.
- **Ring 2 (orchestrator)** — :func:`handle_push_event`. The single
  public entry point. Sequences the DB lookups, the config
  preconditions, and the workflow dispatch.
- **Ring 3 (DB shell)**   — :func:`resolve_installation_owner`,
  :func:`resolve_installed_repo`. Each is the single boundary into the
  database.

Every skip path returns a :class:`PushWebhookAck` with
``accepted=False`` and a ``skip_reason``; the handler never raises so
the router can always reply ``202``.
"""

from __future__ import annotations

import logging
from typing import Any

from dbos import DBOS, SetWorkflowID
from pydantic import BaseModel
from sqlmodel import select

from app.core.db import async_session_maker
from app.models.installation import Installation
from app.models.repo import Repo
from app.services.indexing.incremental.helpers import (
    extract_push_files,
    incremental_workflow_id,
    push_skip_reason,
)
from app.services.indexing.incremental.types import IncrementalIndexWorkflowInput
from app.services.indexing.incremental.workflow import incrementalIndexRepo

log = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# ack                                                                          #
# --------------------------------------------------------------------------- #


class PushWebhookAck(BaseModel):
    """What the orchestrator hands back to the router for logging.

    The router logs the dumped JSON; the response body to GitHub is
    always ``202 Accepted`` regardless of ``accepted``.
    """

    accepted: bool
    action: str = "push"
    delivery: str
    skip_reason: str | None = None


# --------------------------------------------------------------------------- #
# Ring 3 — DB shell                                                            #
# --------------------------------------------------------------------------- #


async def resolve_installation_owner(github_installation_id: int) -> str | None:
    """Return the WorkOS ``user_id`` that owns the installation, or ``None``."""
    async with async_session_maker() as session:
        stmt = select(Installation.user_id).where(
            Installation.github_installation_id == github_installation_id,
            Installation.user_id.is_not(None),  # type: ignore[union-attr]
        )
        return (await session.exec(stmt)).first()


async def resolve_installed_repo(
    *,
    user_id: str,
    repo_owner: str,
    repo_name: str,
) -> Repo | None:
    """Return the local :class:`Repo` row for ``user_id``'s installed repo."""
    async with async_session_maker() as session:
        stmt = select(Repo).where(
            Repo.user_id == user_id,
            Repo.repo_owner == repo_owner,
            Repo.repo_name == repo_name,
        )
        return (await session.exec(stmt)).first()


# --------------------------------------------------------------------------- #
# Ring 2 — orchestrator                                                        #
# --------------------------------------------------------------------------- #


async def handle_push_event(
    payload: dict[str, Any],
    delivery: str,
) -> PushWebhookAck:
    """Dispatch a verified ``push`` delivery to the incremental workflow.

    The router calls this once per delivery that has already passed
    signature verification. Skip reasons (all return ``accepted=False``):

    ``malformed_payload``, ``not_default_branch``, ``deleted_push``,
    ``created_push``, ``missing_head_commit``, ``malformed_installation``,
    ``unowned_installation``, ``repo_not_configured``,
    ``repo_not_indexed``, ``indexing_not_configured``, ``no_file_changes``.
    """
    skip_reason = push_skip_reason(payload)
    if skip_reason is not None:
        return PushWebhookAck(
            accepted=False,
            delivery=delivery,
            skip_reason=skip_reason,
        )

    files = extract_push_files(payload)
    if files is None:
        log.info(
            "incremental.webhook: skip (missing head commit): delivery=%s",
            delivery,
        )
        return PushWebhookAck(
            accepted=False,
            delivery=delivery,
            skip_reason="missing_head_commit",
        )

    installation = payload.get("installation") or {}
    installation_id = installation.get("id")
    if not isinstance(installation_id, int):
        log.info(
            "incremental.webhook: skip (malformed installation): delivery=%s",
            delivery,
        )
        return PushWebhookAck(
            accepted=False,
            delivery=delivery,
            skip_reason="malformed_installation",
        )

    repo = payload.get("repository") or {}
    owner = ((repo.get("owner") or {}).get("login")) if isinstance(repo, dict) else None
    name = repo.get("name") if isinstance(repo, dict) else None
    if not isinstance(owner, str) or not isinstance(name, str):
        log.info(
            "incremental.webhook: skip (malformed repository): delivery=%s",
            delivery,
        )
        return PushWebhookAck(
            accepted=False,
            delivery=delivery,
            skip_reason="malformed_payload",
        )

    user_id = await resolve_installation_owner(installation_id)
    if user_id is None:
        log.info(
            "incremental.webhook: skip (unowned installation): delivery=%s "
            "github_installation_id=%s owner=%s repo=%s",
            delivery,
            installation_id,
            owner,
            name,
        )
        return PushWebhookAck(
            accepted=False,
            delivery=delivery,
            skip_reason="unowned_installation",
        )

    installed_repo = await resolve_installed_repo(
        user_id=user_id,
        repo_owner=owner,
        repo_name=name,
    )
    if installed_repo is None:
        log.info(
            "incremental.webhook: skip (repo not installed): delivery=%s "
            "user_id=%s owner=%s repo=%s",
            delivery,
            user_id,
            owner,
            name,
        )
        return PushWebhookAck(
            accepted=False,
            delivery=delivery,
            skip_reason="repo_not_configured",
        )

    # A repo that never completed a full index has no dataset yet — the
    # full index (setup auto-dispatch or the dashboard button) owns the
    # bootstrap. Incremental runs must not create the table.
    if not installed_repo.is_indexed:
        log.info(
            "incremental.webhook: skip (repo not indexed yet): delivery=%s "
            "owner=%s repo=%s",
            delivery,
            owner,
            name,
        )
        return PushWebhookAck(
            accepted=False,
            delivery=delivery,
            skip_reason="repo_not_indexed",
        )

    files_to_delete = sorted(set(files.removed) | set(files.modified))
    files_to_index = sorted(set(files.added) | set(files.modified))
    if not files_to_delete and not files_to_index:
        log.info(
            "incremental.webhook: skip (no file changes): delivery=%s "
            "owner=%s repo=%s head_sha=%s",
            delivery,
            owner,
            name,
            files.head_sha,
        )
        return PushWebhookAck(
            accepted=False,
            delivery=delivery,
            skip_reason="no_file_changes",
        )

    default_branch = repo.get("default_branch") if isinstance(repo, dict) else None
    clone_url = repo.get("clone_url") if isinstance(repo, dict) else None
    repo_url = (
        clone_url
        if isinstance(clone_url, str)
        else f"https://github.com/{owner}/{name}.git"
    )

    workflow_input = IncrementalIndexWorkflowInput(
        user_id=user_id,
        repo_owner=owner,
        repo_name=name,
        repo_url=repo_url,
        default_branch=default_branch if isinstance(default_branch, str) else None,
        local_repo_id=installed_repo.id,
        head_sha=files.head_sha,
        files_to_delete=files_to_delete,
        files_to_index=files_to_index,
    )

    workflow_id = incremental_workflow_id(owner, name, files.head_sha)

    log.info(
        "incremental.webhook: starting workflow: delivery=%s workflow_id=%s "
        "owner=%s repo=%s head_sha=%s delete=%d index=%d",
        delivery,
        workflow_id,
        owner,
        name,
        files.head_sha,
        len(files_to_delete),
        len(files_to_index),
    )

    with SetWorkflowID(workflow_id):
        await DBOS.start_workflow_async(incrementalIndexRepo, workflow_input)

    return PushWebhookAck(accepted=True, delivery=delivery)


__all__ = [
    "PushWebhookAck",
    "handle_push_event",
    "resolve_installation_owner",
    "resolve_installed_repo",
]
