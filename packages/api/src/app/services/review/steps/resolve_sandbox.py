"""Resolve and connect the active sandbox for a review."""

from __future__ import annotations

import logging

from app.core.result import Err, Ok, Result
from app.core.sandbox.e2b import E2BSandbox, E2BSandboxSpec
from app.models.sandbox import Sandbox as SandboxModel
from app.repositories import Repository
from app.services.review.errors import NoActiveSandbox, SandboxConnectFailed

log = logging.getLogger(__name__)


async def resolve_sandbox(
    *,
    user_id: str,
    repo_id: str,
    repository: Repository[SandboxModel],
    spec: E2BSandboxSpec,
) -> Result[E2BSandbox, NoActiveSandbox | SandboxConnectFailed]:
    """Look up the active sandbox row and connect to the E2B handle.

    "Active" means ``state in {STARTED, PAUSED, STOPPED}`` — any state
    except ``DELETED`` or ``ARCHIVED``. If multiple rows match (data
    integrity issue, but possible) the first one wins and the rest are
    logged.

    Returns:

    - ``Err(NoActiveSandbox)`` when no row matches.
    - ``Err(SandboxConnectFailed)`` when the row exists but the E2B
      ``connect`` call raises.
    """
    sb_record = await repository.find_by_field(SandboxModel.repo_id, repo_id)

    if sb_record is None:
        return Err(NoActiveSandbox(user_id=user_id, repo_id=repo_id))

    try:
        connected = await E2BSandbox.connect(
            sandbox_id=sb_record.id,
            sandbox_name=sb_record.sandbox_name,
            repo_id=repo_id,
            user_id=user_id,
            spec=spec,
            timeout=60 * 60,
            api_key=spec.api_key,
        )
    except Exception as exc:
        log.exception(
            "failed to connect sandbox: user_id=%s repo_id=%s sandbox_id=%s",
            user_id,
            repo_id,
            sb_record.id,
        )
        return Err(
            SandboxConnectFailed(
                user_id=user_id,
                repo_id=repo_id,
                sandbox_id=sb_record.id,
                cause=f"{type(exc).__name__}: {exc}",
            )
        )
    return Ok(connected)


__all__: list[str] = ["resolve_sandbox"]
