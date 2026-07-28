"""Step 6 (in ``finally``): best-effort pause of the E2B sandbox.

The workflow calls this regardless of the outcome of the prior
steps so a process crash mid-step does not leave the sandbox
running. Failures here are logged and swallowed: stopping is
idempotent on the E2B side, and a failed stop would only delay
(not prevent) cleanup.
"""

from __future__ import annotations

import logging
from typing import cast

from dbos import DBOS

from app.core.sandbox.e2b import E2BSandbox, E2BSandboxSpec
from app.core.sandbox.factory import build_default_spec

log = logging.getLogger(__name__)


@DBOS.step()
async def stop_setup_sandbox_step(
    *,
    sandbox_id: str,
    sandbox_name: str,
    repo_id: str,
    user_id: str,
) -> None:
    """Pause the E2B sandbox and mark the row ``STOPPED``.

    Best-effort: any exception is logged and swallowed. The
    :class:`Sandbox` row is updated only if the E2B pause succeeds
    AND the row exists — a missing row is a no-op so the step is
    safe to run on a partially-failed workflow.

    Named with the ``setup_`` infix to avoid clashing with the
    review pipeline's identically-named
    :func:`app.services.review.workflow.stop_sandbox_step` (DBOS
    registers steps by name, not by module).
    """
    spec: E2BSandboxSpec = cast(E2BSandboxSpec, build_default_spec("e2b"))

    try:
        sandbox = await E2BSandbox.connect(
            sandbox_id=sandbox_id,
            sandbox_name=sandbox_name,
            repo_id=repo_id,
            user_id=user_id,
            spec=spec,
            timeout=60 * 2,
            api_key=spec.api_key,
        )
        await sandbox.stop()
    except Exception:
        log.exception(
            "stop_setup_sandbox_step: pause failed: sandbox_id=%s repo_id=%s",
            sandbox_id,
            repo_id,
        )
        raise


__all__ = ["stop_setup_sandbox_step"]
