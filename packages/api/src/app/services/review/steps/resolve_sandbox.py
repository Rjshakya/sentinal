"""Resolve and connect the active sandbox for a review.

Two layers, following the Functional Core / Imperative Shell split:

- :func:`resolve_sandbox` — the **pure** helper. Takes a
  :class:`app.repositories.Repository` and an :class:`E2BSandboxSpec`,
  looks up the active sandbox row, and returns a connected
  :class:`E2BSandbox` handle. No DBOS, no workflow boundary.
- :func:`resolve_sandbox_step` — the **DBOS-wrapped** step. Looks up
  the same row, reconnects to E2B, and returns a
  :class:`app.services.review.workflow_types.SandboxMeta` (the
  serialisable subset that can cross a workflow boundary). Retries up
  to three times on transient connect failures.

"Active" sandbox state means ``state in {STARTED, PAUSED, STOPPED}`` —
any state except ``DELETED`` or ``ARCHIVED``. If multiple rows match
(data integrity issue, but possible) the first one wins and the rest
are logged.
"""

from __future__ import annotations

import logging

from dbos import DBOS
from sqlmodel import select

from app.core.db import async_session_maker
from app.core.sandbox.e2b import E2BSandbox, E2BSandboxSpec
from app.models.sandbox import Sandbox as SandboxModel
from app.repositories import Repository
from app.services.review._internal import _SHOULD_RETRY_TRANSIENT, _e2b_spec
from app.services.review.errors import (
    NoActiveSandboxError,
    SandboxConnectError,
)
from app.services.review.workflow_types import SandboxMeta

log = logging.getLogger(__name__)


async def resolve_sandbox(
    *,
    user_id: str,
    repo_id: str,
    repository: Repository[SandboxModel],
    spec: E2BSandboxSpec,
) -> E2BSandbox:
    """Look up the active sandbox row and connect to the E2B handle.

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


@DBOS.step(
    retries_allowed=True,
    max_attempts=3,
    should_retry=_SHOULD_RETRY_TRANSIENT,
)
async def resolve_sandbox_step(*, user_id: str, repo_id: str) -> SandboxMeta:
    """Durable DBOS step: find the active sandbox row and connect to E2B.

    Returns a :class:`SandboxMeta` (the serialisable subset) so
    the workflow can carry the handle across steps without holding a
    live E2B connection.

    Raises:
        NoActiveSandboxError: no row matches ``repo_id``. Business
            outcome — not retried.
        SandboxConnectError: the row exists but ``E2BSandbox.connect``
            raised. Transient — DBOS retries.
    """
    async with async_session_maker() as session:
        result = await session.exec(
            select(SandboxModel).where(SandboxModel.repo_id == repo_id)
        )
        sb_record = result.one_or_none()
    if sb_record is None:
        raise NoActiveSandboxError(user_id=user_id, repo_id=repo_id)

    spec = _e2b_spec()
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
    return SandboxMeta(
        sandbox_id=connected.id,
        sandbox_name=sb_record.sandbox_name,
    )


__all__ = ["resolve_sandbox", "resolve_sandbox_step"]
