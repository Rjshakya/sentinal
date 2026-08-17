"""DBOS durable step: refresh the sandbox repo to the default branch.

The sandbox working tree is left at whatever commit the setup-time
``git clone`` checked out, so on every later review the on-disk files
are stale relative to the merged history. :func:`update_repo_step`
reconnects to the sandbox, fetches the default branch, and hard-resets
the working tree to its remote tip — giving the review agents fresh
``read_file`` context. The unified diff itself is SHA-based
(``git diff base_sha...head_sha`` in :mod:`app.services.review.diff`),
so it is unaffected by the working tree state.

``git reset --hard`` (rather than ``checkout`` + ``pull``) is the
deterministic "make the working tree equal the remote branch tip"
operation: it survives dirty trees, divergent local branches, and
missing tracking configuration, and it discards any local changes the
agents may have left behind (the sandbox is a scratch space, never a
source of truth).
"""

from __future__ import annotations

import logging

from dbos import DBOS

from app.core.sandbox import BaseSandbox
from app.core.sandbox.e2b import E2BSandbox
from app.services.review._internal import _SHOULD_RETRY_TRANSIENT, _e2b_spec
from app.services.review.diff import truncate_diff_output
from app.services.review.errors import RepoUpdateError, SandboxConnectError
from app.services.review.helpers import get_repo_path

log = logging.getLogger(__name__)

FETCH_TIMEOUT_S: float = 120.0
"""Upper bound on the wall-clock duration of ``git fetch``."""
RESET_TIMEOUT_S: float = 120.0
"""Upper bound on the wall-clock duration of ``git reset --hard``."""


async def update_repo(
    *,
    sandbox: BaseSandbox,
    repo_id: str,
    repo_path_str: str,
    default_branch: str,
) -> None:
    """Fetch the default branch and hard-reset the working tree to it.

    Runs ``git fetch origin <default_branch>`` followed by
    ``git reset --hard origin/<default_branch>`` inside the sandbox.

    Raises:
        RepoUpdateError: when either sub-command returns a non-zero
            exit code. Business outcome — not retried.
    """
    fetch = await sandbox.execute(
        f"git fetch origin {default_branch}",
        cwd=repo_path_str,
        timeout=FETCH_TIMEOUT_S,
    )
    if fetch.exit_code != 0:
        raise RepoUpdateError(
            repo_id=repo_id,
            branch=default_branch,
            cause=f"git fetch exited {fetch.exit_code}: "
            f"{truncate_diff_output(fetch.stderr or fetch.stdout or '')}",
        )

    reset = await sandbox.execute(
        f"git reset --hard origin/{default_branch}",
        cwd=repo_path_str,
        timeout=RESET_TIMEOUT_S,
    )
    if reset.exit_code != 0:
        raise RepoUpdateError(
            repo_id=repo_id,
            branch=default_branch,
            cause=f"git reset exited {reset.exit_code}: "
            f"{truncate_diff_output(reset.stderr or reset.stdout or '')}",
        )

    log.info(
        "Updated repo to default branch: repo_id=%s branch=%s",
        repo_id,
        default_branch,
    )


@DBOS.step(
    retries_allowed=True,
    max_attempts=3,
    should_retry=_SHOULD_RETRY_TRANSIENT,
)
async def update_repo_step(
    *,
    sandbox_id: str,
    sandbox_name: str,
    repo_id: str,
    repo_name: str,
    user_id: str,
    default_branch: str | None,
) -> None:
    """Durable step: reconnect to the sandbox and refresh the repo tree.

    When ``default_branch`` is ``None`` (the repo row has no recorded
    default branch) the step is a no-op — the review still works
    because the diff is computed from explicit SHAs.

    Raises:
        SandboxConnectError: reconnect to E2B failed.
            :class:`TransientStepError` — DBOS retries.
        RepoUpdateError: ``git fetch`` / ``git reset`` returned a
            non-zero exit code. Business outcome — not retried.
    """
    if default_branch is None:
        log.info(
            "update_repo_step: skipped (no default branch on repo row): "
            "repo_id=%s",
            repo_id,
        )
        return

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
            cause=f"failed to reconnect sandbox for repo update: {type(exc).__name__}: {exc}",
        ) from exc

    try:
        await update_repo(
            sandbox=sandbox,
            repo_id=repo_id,
            repo_path_str=get_repo_path(repo_name),
            default_branch=default_branch,
        )
    finally:
        try:
            await sandbox.stop()
        except Exception:
            log.exception("failed to stop sandbox after repo update")


__all__ = ["update_repo", "update_repo_step"]