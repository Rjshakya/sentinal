"""Delete the cloned repo from the sandbox (best-effort cleanup).

The repair pipeline clones the repo (reusing the review pipeline's
``cloneRepoStep``) only to produce the diff via ``git diff``; the
clone is not needed afterwards. This step removes it, so the sandbox
holds only the diff artefacts at ``{diff_dir}/`` while the repair
agent works.

Layers:

- :func:`deleteRepo` — the **value-returning** worker: runs ``rm -rf``
  on the repo path in the sandbox, returns ``None`` or a
  :class:`DeleteRepoError` value.
- :func:`deleteRepoStep` — the **DBOS-wrapped** step edge. Best-effort
  like :func:`app.workflows.review.steps.kill_sandbox.killSandboxStep`:
  failures are logged, never raised — a cleanup failure must not mask
  the run's outcome.
"""

from __future__ import annotations

import logging
import shlex

from dbos import DBOS
from deepagents.backends.sandbox import BaseSandbox

from app.services.sandbox.types import SandboxCtx
from app.utils.branded import RepoName
from app.workflows.repair_and_publish.errors import DeleteRepoError
from app.workflows.review.errors import SandboxConnectError
from app.workflows.review.steps._helpers import (
    asAsyncSandbox,
    connectSandbox,
    getRepoPath,
    truncateOutput,
)

log = logging.getLogger(__name__)

_RM_TIMEOUT_S = 60


async def deleteRepo(
    sandbox: BaseSandbox,
    *,
    repoName: RepoName,
) -> None | DeleteRepoError:
    """Remove the cloned repo directory from the sandbox."""
    repoPath = getRepoPath(repoName)
    backend = asAsyncSandbox(sandbox)

    try:
        result = await backend.aexecute(
            f"rm -rf {shlex.quote(repoPath)}",
            timeout=_RM_TIMEOUT_S,
        )
    except Exception as exc:
        return DeleteRepoError(
            message=f"rm -rf failed: {type(exc).__name__}: {exc}",
        )
    if result.exit_code != 0:
        return DeleteRepoError(
            message=(
                f"rm -rf exited {result.exit_code}: {truncateOutput(result.output)}"
            ),
        )
    return None


@DBOS.step(name="repair_delete_repo_step")
async def deleteRepoStep(
    *,
    sandboxCtx: SandboxCtx,
    repoName: RepoName,
) -> None:
    """Durable step: remove the cloned repo from the sandbox.

    Best-effort cleanup: failures are logged, never raised.
    """
    sandbox = await connectSandbox(sandboxCtx)
    if isinstance(sandbox, SandboxConnectError):
        log.warning(
            "delete_repo_step: sandbox reconnect failed (continuing): "
            "sandbox_id=%s cause=%s",
            sandboxCtx.sandboxId,
            sandbox.message,
        )
        return

    result = await deleteRepo(sandbox, repoName=repoName)
    if isinstance(result, DeleteRepoError):
        log.warning(
            "delete_repo_step: failed to delete repo (continuing): "
            "repo_name=%s sandbox_id=%s cause=%s",
            repoName,
            sandboxCtx.sandboxId,
            result.message,
        )
        return

    log.info(
        "delete_repo_step: ok repo_name=%s sandbox_id=%s",
        repoName,
        sandboxCtx.sandboxId,
    )


__all__ = ["deleteRepo", "deleteRepoStep"]