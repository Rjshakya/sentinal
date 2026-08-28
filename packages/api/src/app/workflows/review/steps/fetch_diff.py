"""Fetch the unified PR diff into the sandbox.

The diff is written to ``/home/user/tmp/{pr_number}/{head_sha}/file.diff``
so the review agents can read it via the ``get_diff`` tool. The split
step then turns it into the per-file annotated chunks.

Layers:

- :func:`fetchDiff` — the value-returning worker: takes the connected
  sandbox handle and the diff range, returns the diff file path (or a
  :class:`DiffResult` carrying a best-effort fetch failure) or a
  :class:`DiffUnavailableError` value.
- :func:`fetchDiffStep` — the DBOS step edge: connects the sandbox,
  runs :func:`fetchDiff`, and raises for retryable / final failures.

``diffBaseSha`` narrows the range for an incremental re-review; when
set, ``git diff {diffBaseSha}...{headSha}`` is produced instead of
``git diff {baseSha}...{headSha}``.
"""

from __future__ import annotations

import logging
import shlex

from dbos import DBOS
from deepagents.backends.sandbox import BaseSandbox
from pydantic import BaseModel

from app.services.sandbox.types import SandboxCtx
from app.utils.branded import CommitId, PRNumber, RepoId
from app.workflows.review.errors import (
    DiffUnavailableError,
    ReviewStepFailure,
    SandboxConnectError,
    TransientReviewStepFailure,
    shouldRetry,
)
from app.workflows.review.steps._helpers import (
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
    """Outcome of :func:`fetchDiff`: the diff was written, possibly
    without a successful ``git fetch origin`` (best-effort catch-all
    for unreachable PR heads)."""

    diffFile: str
    fetchFailed: bool = False


async def fetchDiff(
    sandbox: BaseSandbox,
    *,
    repoId: RepoId,
    repoName: str,
    prNumber: PRNumber,
    headSha: CommitId,
    baseSha: str,
    diffBaseSha: CommitId | None,
) -> DiffResult | DiffUnavailableError:
    """Fetch the unified diff and write it to the sandbox.

    Returns the sandbox path of the saved ``file.diff``; the diff body
    itself is not returned to the workflow — the agents re-read it via
    the deepagents backend's ``read_file`` tool.
    """
    repoPath = getRepoPath(repoName)
    diffDir = getReviewDiffDirPath(prNumber, headSha)
    diffFile = f"{diffDir}/file.diff"
    backend = asAsyncSandbox(sandbox)

    mkdir = await backend.aexecute(
        f"mkdir -p {shlex.quote(diffDir)}",
        timeout=_MKDIR_TIMEOUT_S,
    )
    if mkdir.exit_code != 0:
        return DiffUnavailableError(
            message=f"mkdir -p failed: {truncateOutput(mkdir.output)}",
            repoId=repoId,
            prNumber=prNumber,
            headSha=headSha,
        )

    fetch = await backend.aexecute(
        f"cd {shlex.quote(repoPath)} && git fetch origin",
        timeout=_FETCH_TIMEOUT_S,
    )

    effectiveBase = diffBaseSha or baseSha
    diff = await backend.aexecute(
        f"cd {shlex.quote(repoPath)} && "
        f"git diff {effectiveBase}...{headSha} > {diffFile}",
        timeout=_DIFF_TIMEOUT_S,
    )
    if diff.exit_code != 0:
        tail = truncateOutput(diff.output)
        return DiffUnavailableError(
            message=f"git diff exited {diff.exit_code}: {tail}",
            repoId=repoId,
            prNumber=prNumber,
            headSha=headSha,
        )

    return DiffResult(diffFile=diffFile, fetchFailed=fetch.exit_code != 0)


@DBOS.step(
    retries_allowed=True,
    max_attempts=3,
    should_retry=shouldRetry,
    backoff_rate=2,
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
    """Durable step: reconnect to the sandbox and fetch the unified diff.

    Raises:
        TransientReviewStepFailure: sandbox reconnect failed.
        ReviewStepFailure: ``git diff`` (or ``mkdir``) returned a
            non-zero exit code. Business outcome — not retried.
    """
    sandbox = await connectSandbox(sandboxCtx)
    if isinstance(sandbox, SandboxConnectError):
        raise TransientReviewStepFailure(sandbox)

    result = await fetchDiff(
        sandbox,
        repoId=repoId,
        repoName=repoName,
        prNumber=prNumber,
        headSha=headSha,
        baseSha=baseSha,
        diffBaseSha=diffBaseSha,
    )
    if isinstance(result, DiffUnavailableError):
        raise ReviewStepFailure(result)

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


__all__ = ["DiffResult", "fetchDiff", "fetchDiffStep"]