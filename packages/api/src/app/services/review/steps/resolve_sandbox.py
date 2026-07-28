"""Resolve and connect the active sandbox for a review."""

from __future__ import annotations

import logging

from app.core.sandbox.e2b import E2BSandbox, E2BSandboxSpec
from app.models.sandbox import Sandbox as SandboxModel
from app.repositories import Repository
from app.services.review.errors import (
    NoActiveSandboxError,
    SandboxConnectError,
)

log = logging.getLogger(__name__)


async def resolve_sandbox(
    *,
    user_id: str,
    repo_id: str,
    repository: Repository[SandboxModel],
    spec: E2BSandboxSpec,
) -> E2BSandbox:
    """Look up the active sandbox row and connect to the E2B handle.

    "Active" means ``state in {STARTED, PAUSED, STOPPED}`` — any state
    except ``DELETED`` or ``ARCHIVED``. If multiple rows match (data
    integrity issue, but possible) the first one wins and the rest are
    logged.

    Raises:
        NoActiveSandboxError: no row matches ``repo_id``.
        SandboxConnectError: the row exists but ``E2BSandbox.connect``
            raised. This is a :class:`TransientStepError` so DBOS
            retries the step.
    """
    sb_record = await repository.find_by_field(SandboxModel.repo_id, repo_id)

    if sb_record is None:
        raise NoActiveSandboxError(user_id=user_id, repo_id=repo_id)

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
        log.warning(
            "sandbox connect failed (will retry): user_id=%s repo_id=%s "
            "sandbox_id=%s cause=%s: %s",
            user_id,
            repo_id,
            sb_record.id,
            type(exc).__name__,
            exc,
        )
        raise SandboxConnectError(
            user_id=user_id,
            repo_id=repo_id,
            sandbox_id=sb_record.id,
            cause=f"{type(exc).__name__}: {exc}",
        ) from exc
    return connected


__all__ = ["resolve_sandbox"]
