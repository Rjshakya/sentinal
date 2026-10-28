"""Fetch the unified PR diff into the sandbox review dir.

Writes ``file.diff`` under ``getDiffDir(headSha)`` — the input the
split step and the pi agents read. ``diffBaseSha`` narrows the range
for an incremental re-review (``{diffBase}...{head}``); otherwise the
range is ``{base}...{head}``. A failed ``git fetch`` is recorded and
tolerated (the local clone may already have the refs); a failed diff
fails the step.
"""

from __future__ import annotations

import shlex

from app.services.sandbox.errors import SandboxProviderError
from app.services.sandbox.service import getProvider
from app.services.sandbox.types import BaseSandbox, SandboxCtx
from app.utils.branded import CommitId, RepoName
from app.utils.sandbox_fs import getDiffDir, getDiffFile, getRepoDir
from app.workflows.review_v3.errors import DiffError
from app.workflows.review_v3.types import DiffResult

_MKDIR_TIMEOUT_S = 30
_FETCH_TIMEOUT_S = 120
_DIFF_TIMEOUT_S = 120
_ERROR_CHARS = 500


async def fetchDiff(
    *,
    sandboxCtx: SandboxCtx,
    repoName: RepoName,
    baseSha: str,
    headSha: CommitId,
    diffBaseSha: CommitId | None,
) -> DiffResult | DiffError:
    """Reconnect and write the unified diff for the run's range."""
    if not baseSha:
        raise ValueError("baseSha must be non-empty")
    if not str(headSha):
        raise ValueError("headSha must be non-empty")
    try:
        provider = getProvider(sandboxCtx.providerId)
    except Exception as exc:
        return DiffError(
            message=f"unknown sandbox provider: {type(exc).__name__}: {exc}",
            retryable=True,
        )
    try:
        made = await provider(ctx=sandboxCtx).create()
    except Exception as exc:
        return DiffError(
            message=f"sandbox reconnect raised {type(exc).__name__}: {exc}",
            retryable=True,
        )
    if isinstance(made, SandboxProviderError):
        return DiffError(
            message=f"sandbox reconnect failed: {made.message}", retryable=True
        )
    backend: BaseSandbox = made

    repoDir = getRepoDir(str(repoName))
    diffDir = getDiffDir(str(headSha))
    diffFile = getDiffFile(str(headSha))

    try:
        mkdir = await backend.aexecute(
            f"mkdir -p {shlex.quote(diffDir)}", timeout=_MKDIR_TIMEOUT_S
        )
    except Exception as exc:
        return DiffError(
            message=f"mkdir raised {type(exc).__name__}: {exc}", retryable=True
        )
    if mkdir.exit_code != 0:
        return DiffError(
            message=f"mkdir diff dir failed: {mkdir.output.strip()[-_ERROR_CHARS:]}"
        )

    try:
        fetch = await backend.aexecute(
            f"git -C {shlex.quote(repoDir)} fetch origin",
            timeout=_FETCH_TIMEOUT_S,
        )
    except Exception as exc:
        return DiffError(
            message=f"git fetch raised {type(exc).__name__}: {exc}", retryable=True
        )

    fro = str(diffBaseSha) if diffBaseSha is not None else baseSha
    try:
        diff = await backend.aexecute(
            f"git -C {shlex.quote(repoDir)} diff {shlex.quote(fro)}..."
            f"{shlex.quote(str(headSha))} > {shlex.quote(diffFile)}",
            timeout=_DIFF_TIMEOUT_S,
        )
    except Exception as exc:
        return DiffError(
            message=f"git diff raised {type(exc).__name__}: {exc}", retryable=True
        )
    if diff.exit_code != 0:
        return DiffError(
            message=f"git diff exited {diff.exit_code}: "
            f"{diff.output.strip()[-_ERROR_CHARS:]}"
        )
    return DiffResult(diffFile=diffFile, fetchFailed=fetch.exit_code != 0)


__all__ = ["DiffResult", "fetchDiff"]
