"""Internal shared helpers for the indexing steps.

Only the sandbox reconnect helper lives here — the pure, testable
functions live in :mod:`app.services.indexing.helpers`.
"""

from __future__ import annotations

import logging

from app.core.sandbox.e2b import E2BSandbox, E2BSandboxSpec
from app.core.sandbox.factory import build_default_spec
from app.services.indexing.errors import IndexSandboxConnectError
from app.services.indexing.types import IndexContext

log = logging.getLogger(__name__)

CONNECT_TIMEOUT_S: int = 60 * 60
"""Upper bound for :meth:`E2BSandbox.connect` in each step."""


def _index_repo_id(ctx: IndexContext) -> str:
    """The repo id passed to the sandbox adapter (never persisted)."""
    return f"index:{ctx.repo_owner}:{ctx.repo_name}"


async def connect_index_sandbox(ctx: IndexContext) -> E2BSandbox:
    """Reconnect to the workflow's sandbox by id.

    Each step reconnects (the in-process handle never crosses a DBOS
    workflow boundary), wrapping failures in
    :class:`IndexSandboxConnectError` so the step-level retry policy
    re-runs the step.

    Raises:
        IndexSandboxConnectError: the reconnect failed. Transient —
            DBOS retries.
    """
    spec: E2BSandboxSpec = build_default_spec("e2b")
    try:
        return await E2BSandbox.connect(
            sandbox_id=ctx.sandbox_id,
            sandbox_name=ctx.sandbox_name,
            repo_id=_index_repo_id(ctx),
            user_id=ctx.user_id,
            spec=spec,
            timeout=CONNECT_TIMEOUT_S,
            api_key=spec.api_key,
        )
    except Exception as exc:
        log.warning(
            "index sandbox connect failed (will retry): sandbox_id=%s "
            "owner=%s repo=%s cause=%s: %s",
            ctx.sandbox_id,
            ctx.repo_owner,
            ctx.repo_name,
            type(exc).__name__,
            exc,
        )
        raise IndexSandboxConnectError(
            cause=f"{type(exc).__name__}: {exc}"
        ) from exc
