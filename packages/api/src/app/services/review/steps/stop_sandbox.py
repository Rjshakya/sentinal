"""DBOS durable steps: best-effort sandbox stop / kill.

- :func:`stop_sandbox_step` — **pause** the sandbox (legacy path; the
  setup-time per-repo sandbox used to be paused after each review).
- :func:`kill_sandbox_step` — **destroy** the sandbox. The stateless
  review pipeline creates a fresh ephemeral sandbox per run and the
  workflow's ``finally`` destroys it with this step, so no paused
  sandboxes accumulate.

Both reconnect to the E2B sandbox by id and swallow every exception
(connect failure, stop failure) with a log line — cleanup must never
mask the real outcome of the review.
"""

from __future__ import annotations

import logging

from dbos import DBOS

from app.core.sandbox.e2b import E2BSandbox
from app.services.review._internal import _e2b_spec

log = logging.getLogger(__name__)


@DBOS.step()
async def stop_sandbox_step(
    *, sandbox_id: str, sandbox_name: str, repo_id: str, user_id: str
) -> None:
    """Durable step: pause the E2B sandbox. Failures are logged, not raised.

    This step is best-effort: stopping is idempotent on the E2B side
    and a failure here would only delay (not prevent) cleanup. The
    outer workflow's ``finally`` block calls it; we never want a
    cleanup failure to mask the real outcome of the review.
    """
    spec = _e2b_spec()
    try:
        sandbox = await E2BSandbox.connect(
            sandbox_id=sandbox_id,
            sandbox_name=sandbox_name,
            repo_id=repo_id,
            user_id=user_id,
            spec=spec,
            timeout=60 * 60,
            api_key=spec.api_key,
        )
        await sandbox.stop()
    except Exception:
        log.exception("failed to stop sandbox: sandbox_id=%s", sandbox_id)


@DBOS.step()
async def kill_sandbox_step(
    *, sandbox_id: str, sandbox_name: str, repo_id: str, user_id: str
) -> None:
    """Durable step: destroy the ephemeral E2B sandbox. Failures are logged.

    Best-effort like :func:`stop_sandbox_step` but **destroys** the
    sandbox instead of pausing it — the stateless review pipeline owns
    the sandbox for one run, so pausing would leak resources. Killing is
    idempotent on the E2B side (killing a dead sandbox is a no-op).
    """
    spec = _e2b_spec()
    try:
        sandbox = await E2BSandbox.connect(
            sandbox_id=sandbox_id,
            sandbox_name=sandbox_name,
            repo_id=repo_id,
            user_id=user_id,
            spec=spec,
            timeout=60 * 60,
            api_key=spec.api_key,
        )
        await sandbox.kill()
    except Exception:
        log.exception("failed to kill sandbox: sandbox_id=%s", sandbox_id)


__all__ = ["kill_sandbox_step", "stop_sandbox_step"]
