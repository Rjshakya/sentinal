"""DBOS durable step: fetch the unified PR diff into the sandbox.

The diff is written to ``/home/user/tmp/{pr_number}/{head_sha}/file.diff``
by :func:`app.services.review.diff.fetch_diff`. The step reconnects to
the E2B sandbox, calls ``fetch_diff``, and stops the sandbox in a
``finally`` so a transient git failure does not leak the connection.
"""

from __future__ import annotations

import logging

from dbos import DBOS

from app.core.sandbox.e2b import E2BSandbox
from app.services.review._internal import _SHOULD_RETRY_TRANSIENT, _e2b_spec
from app.services.review.diff import fetch_diff
from app.services.review.errors import SandboxConnectError
from app.services.review.helpers import get_repo_path

log = logging.getLogger(__name__)


@DBOS.step(
    retries_allowed=True,
    max_attempts=3,
    should_retry=_SHOULD_RETRY_TRANSIENT,
)
async def fetch_diff_step(
    *,
    sandbox_id: str,
    sandbox_name: str,
    repo_id: str,
    repo_name: str,
    user_id: str,
    pr_number: int,
    base_sha: str,
    head_sha: str,
) -> str:
    """Durable step: reconnect to the sandbox and fetch the unified diff.

    Returns the sandbox path of the saved ``file.diff``. The actual diff
    body is not returned to the workflow — the agent re-reads it via the
    deepagents backend's ``read_file`` tool.

    Raises:
        SandboxConnectError: reconnect to E2B failed.
            :class:`TransientStepError` — DBOS retries.
        DiffUnavailableError: ``git diff`` (or ``mkdir``) returned a
            non-zero exit code. Business outcome — not retried.
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
    except Exception as exc:
        raise SandboxConnectError(
            user_id=user_id,
            repo_id=repo_id,
            sandbox_id=sandbox_id,
            cause=f"failed to reconnect sandbox for diff: {type(exc).__name__}: {exc}",
        ) from exc

    try:
        return await fetch_diff(
            sandbox=sandbox,
            repo_id=repo_id,
            repo_path_str=get_repo_path(repo_name),
            pr_number=pr_number,
            base_sha=base_sha,
            head_sha=head_sha,
        )
    finally:
        try:
            await sandbox.stop()
        except Exception:
            log.exception("failed to stop sandbox after diff fetch")


__all__ = ["fetch_diff_step"]
