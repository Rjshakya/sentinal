"""Fetch the unified PR diff into the sandbox.

The diff is written to ``/home/user/tmp/{pr_number}/{head_sha}/file.diff``
as the split step's input; the agents never read it. ``diffBaseSha``
narrows the range for an incremental re-review; when set,
``git diff {diffBaseSha}...{headSha}`` is produced instead of
``git diff {baseSha}...{headSha}``.
"""

from __future__ import annotations

import logging
import shlex

from pydantic import BaseModel

from app.services.sandbox.types import SandboxCtx
from app.utils.branded import CommitId, PRNumber, RepoId
from app.workflows.review_v2.errors import (
    DiffUnavailableError,
    ReviewStepFailure,
    SandboxConnectError,
    TransientReviewStepFailure,
)
from app.workflows.review_v2.steps._helpers import (
    asAsyncSandbox,
    connectSandbox,
    getRepoPath,
    getReviewDiffDirPath,
    truncateOutput,
)

log = logging.getLogger(__name__)

_MKDIR_TIMEOUT_S = 30
_FETCH_TIMEOUT_S = 120
_DIFF_TIMEOUT_S = 120


class DiffResult(BaseModel):
    """The diff was written, possibly without a successful ``git fetch``."""

    diffFile: str
    fetchFailed: bool = False


def diffUnavailable(
    message: str, *, repoId: RepoId, prNumber: PRNumber, headSha: CommitId
) -> ReviewStepFailure:
    return ReviewStepFailure(
        DiffUnavailableError(
            message=message,
            repoId=repoId,
            prNumber=prNumber,
            headSha=headSha,
        )
    )


async def fetchDiffStep(
    *,
    sandboxCtx: SandboxCtx,
    repoId: RepoId,
    repoName: str,
    prNumber: PRNumber,
    headSha: CommitId,
    baseSha: str,
    diffBaseSha: CommitId | None,
) -> DiffResult:
    """Reconnect to the sandbox and fetch the unified diff.

    Raises:
        TransientReviewStepFailure: sandbox reconnect failed.
        ReviewStepFailure: ``git diff`` (or ``mkdir``) returned a
            non-zero exit code.
    """
    sandbox = await connectSandbox(sandboxCtx)
    if isinstance(sandbox, SandboxConnectError):
        raise TransientReviewStepFailure(sandbox)
    backend = asAsyncSandbox(sandbox)

    repoPath = getRepoPath(repoName)
    diffDir = getReviewDiffDirPath(prNumber, headSha)
    diffFile = f"{diffDir}/file.diff"

    mkdir = await backend.aexecute(
        f"mkdir -p {shlex.quote(diffDir)}",
        timeout=_MKDIR_TIMEOUT_S,
    )
    if mkdir.exit_code != 0:
        raise diffUnavailable(
            f"mkdir -p failed: {truncateOutput(mkdir.output)}",
            repoId=repoId,
            prNumber=prNumber,
            headSha=headSha,
        )

    fetch = await backend.aexecute(
        f"cd {shlex.quote(repoPath)} && git fetch origin",
        timeout=_FETCH_TIMEOUT_S,
    )

    diff = await backend.aexecute(
        f"cd {shlex.quote(repoPath)} && "
        f"git diff {diffBaseSha or baseSha}...{headSha} > {diffFile}",
        timeout=_DIFF_TIMEOUT_S,
    )
    if diff.exit_code != 0:
        raise diffUnavailable(
            f"git diff exited {diff.exit_code}: {truncateOutput(diff.output)}",
            repoId=repoId,
            prNumber=prNumber,
            headSha=headSha,
        )

    result = DiffResult(diffFile=diffFile, fetchFailed=fetch.exit_code != 0)
    if result.fetchFailed:
        log.warning(
            "fetch_diff_step: git fetch origin failed (continuing): "
            "pr_number=%s repo_id=%s",
            prNumber,
            repoId,
        )
    log.info(
        "fetch_diff_step: ok pr_number=%s path=%s",
        prNumber,
        result.diffFile,
    )
    return result


__all__ = ["DiffResult", "fetchDiffStep"]
