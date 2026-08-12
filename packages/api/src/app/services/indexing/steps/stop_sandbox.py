"""Step 7 (finally): kill the ephemeral index sandbox.

Best-effort teardown: the sandbox is created for this run only and
must not linger. Runs in the workflow's ``finally`` so it executes on
every outcome; failures are logged, never raised (a failed teardown
must not mask the workflow's real result).
"""

from __future__ import annotations

import logging

from dbos import DBOS

from app.services.indexing.steps._internal import connect_index_sandbox
from app.services.indexing.types import IndexContext

log = logging.getLogger(__name__)


@DBOS.step()
async def stopIndexerSandbox(*, ctx: IndexContext) -> None:
    """Kill the sandbox, tolerating every failure mode.

    If the sandbox is already gone (connect fails), that is the
    desired end state — log and return.
    """
    try:
        sandbox = await connect_index_sandbox(ctx)
    except Exception:  # noqa: BLE001 — best-effort teardown: a missing sandbox is the desired state
        log.info(
            "stop_index_sandbox: sandbox already gone: sandbox_id=%s",
            ctx.sandbox_id,
        )
        return
    try:
        await sandbox.stop()
    except Exception:
        log.exception(
            "stop_index_sandbox: kill failed: sandbox_id=%s",
            ctx.sandbox_id,
        )


__all__ = ["stopIndexerSandbox"]
