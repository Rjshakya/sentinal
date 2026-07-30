"""DBOS durable step: best-effort sandbox stop.

Reconnects to the E2B sandbox by id and calls ``sandbox.stop()``. Any
exception (connect failure, stop failure) is logged and swallowed —
this step is the workflow's cleanup hook and a stop failure should
never mask the real outcome of the review.
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
    """Durable step: stop the E2B sandbox. Failures are logged, not raised.

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


__all__ = ["stop_sandbox_step"]
