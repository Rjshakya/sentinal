"""Split the fetched diff into per-file annotated chunks.

Connects to the sandbox, uploads the in-sandbox
:file:`scripts/split_diff.py` (read as bytes on the host), and runs it
against ``file.diff``. The script writes ``overview.md`` and the
per-file annotated chunks under ``splitted_diffs/`` next to the diff,
and prints one compact JSON line to stdout — the tiny split summary
parsed by :func:`parseSplitSummary`.

Exit-code contract: ``0`` success (stdout is the summary JSON), ``124``
(timeout) / ``-1`` (runner dropout) transient — DBOS retries — and
``>0`` script failure (business outcome — the diff cannot be split).

Layers:

- :func:`parseSplitSummary` — pure stdout parser (shared with tests).
- :func:`splitDiff` — the value-returning worker.
- :func:`splitDiffStep` — the DBOS step edge.
"""

from __future__ import annotations

import json
import logging
import shlex
from pathlib import Path

from dbos import DBOS
from deepagents.backends.sandbox import BaseSandbox

from app.services.sandbox.types import SandboxCtx
from app.utils.branded import CommitId, PRNumber, RepoId
from app.workflows.review.errors import (
    DiffSplitError,
    DiffSplitSetupError,
    ReviewStepFailure,
    SandboxConnectError,
    TransientReviewStepFailure,
    shouldRetry,
)
from app.workflows.review.steps._helpers import (
    asAsyncSandbox,
    connectSandbox,
    getReviewDiffDirPath,
    truncateOutput,
)
from app.workflows.review.types import SplitDiffResult

log = logging.getLogger(__name__)

_SCRIPTS_DIR: Path = Path(__file__).resolve().parent.parent / "scripts"
"""Directory holding the in-sandbox scripts; the host reads them as bytes."""

_SCRIPT_REMOTE_PATH = "/home/user/split_diff.py"
"""Where the split script lands inside the sandbox."""

_RUN_TIMEOUT_S = 60


def parseSplitSummary(stdout: str) -> SplitDiffResult:
    """Parse and validate the script's single stdout JSON line.

    Raises:
        ValueError: the stdout is not a single JSON object with a
            boolean ``overview_written``, a non-negative
            ``files_changed``, and a string-list ``skipped``.
    """
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise ValueError(f"split summary is not valid JSON: {stdout[:200]!r}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"split summary is not a JSON object: {stdout[:200]!r}")

    overview_written = data.get("overview_written")
    if not isinstance(overview_written, bool):
        raise ValueError(
            f"split summary has no boolean overview_written: {stdout[:200]!r}"
        )
    files_changed = data.get("files_changed")
    if not isinstance(files_changed, int) or files_changed < 0:
        raise ValueError(
            f"split summary has no non-negative files_changed: {stdout[:200]!r}"
        )
    skipped = data.get("skipped")
    if not isinstance(skipped, list) or not all(isinstance(s, str) for s in skipped):
        raise ValueError(f"split summary has no string-list skipped: {stdout[:200]!r}")

    return SplitDiffResult(
        overview_written=overview_written,
        files_changed=files_changed,
        skipped=skipped,
    )


async def splitDiff(
    sandbox: BaseSandbox,
    *,
    repoId: RepoId,
    prNumber: PRNumber,
    headSha: CommitId,
) -> SplitDiffResult | DiffSplitSetupError | DiffSplitError:
    """Upload the split script and run it against ``file.diff``."""
    diffDir = getReviewDiffDirPath(prNumber, headSha)
    diffFile = f"{diffDir}/file.diff"
    backend = asAsyncSandbox(sandbox)

    script_src = _SCRIPTS_DIR / "split_diff.py"
    try:
        uploads = await backend.aupload_files(
            [(_SCRIPT_REMOTE_PATH, script_src.read_bytes())]
        )
        upload_error = next((u.error for u in uploads if u.error is not None), None)
        if upload_error is not None:
            return DiffSplitSetupError(
                message=f"failed to upload split script: {upload_error}",
                repoId=repoId,
                prNumber=prNumber,
                headSha=headSha,
            )
    except Exception as exc:
        return DiffSplitSetupError(
            message=f"failed to upload split script: {type(exc).__name__}: {exc}",
            repoId=repoId,
            prNumber=prNumber,
            headSha=headSha,
        )

    try:
        result = await backend.aexecute(
            f"python3 {shlex.quote(_SCRIPT_REMOTE_PATH)} "
            f"{shlex.quote(diffFile)} {shlex.quote(diffDir)} "
            f"--pr {prNumber} --commit {headSha}",
            timeout=_RUN_TIMEOUT_S,
        )
    except Exception as exc:
        return DiffSplitSetupError(
            message=f"failed to run split script: {type(exc).__name__}: {exc}",
            repoId=repoId,
            prNumber=prNumber,
            headSha=headSha,
        )

    if result.exit_code in (-1, 124):
        return DiffSplitSetupError(
            message=f"runner dropped the split script (exit {result.exit_code})",
            repoId=repoId,
            prNumber=prNumber,
            headSha=headSha,
        )
    if result.exit_code != 0:
        tail = truncateOutput(result.output)
        return DiffSplitError(
            message=f"split script exited {result.exit_code}: {tail}",
            repoId=repoId,
            prNumber=prNumber,
            headSha=headSha,
        )

    try:
        return parseSplitSummary(result.output.strip())
    except ValueError as exc:
        return DiffSplitError(
            message=f"split summary unparseable: {exc}",
            repoId=repoId,
            prNumber=prNumber,
            headSha=headSha,
        )


@DBOS.step(
    retries_allowed=True,
    max_attempts=3,
    should_retry=shouldRetry,
    backoff_rate=2,
)
async def splitDiffStep(
    *,
    sandboxCtx: SandboxCtx,
    repoId: RepoId,
    prNumber: PRNumber,
    headSha: CommitId,
) -> SplitDiffResult:
    """Durable step: split ``file.diff`` into per-file chunks.

    On success the sandbox holds ``overview.md`` and the
    ``splitted_diffs/`` chunks; the returned :class:`SplitDiffResult`
    carries the tiny split summary without the diff text.

    Raises:
        TransientReviewStepFailure: sandbox reconnect / script upload /
            runner dropout failed. DBOS retries.
        ReviewStepFailure: the script exited non-zero or printed no
            parseable summary. Business outcome — not retried.
    """
    sandbox = await connectSandbox(sandboxCtx)
    if isinstance(sandbox, SandboxConnectError):
        raise TransientReviewStepFailure(sandbox)

    result = await splitDiff(
        sandbox,
        repoId=repoId,
        prNumber=prNumber,
        headSha=headSha,
    )
    if isinstance(result, DiffSplitSetupError):
        raise TransientReviewStepFailure(result)
    if isinstance(result, DiffSplitError):
        raise ReviewStepFailure(result)

    log.info(
        "split_diff_step: ok pr_number=%s files_changed=%d skipped=%d",
        prNumber,
        result["files_changed"],
        len(result["skipped"]),
    )
    return result


__all__ = ["parseSplitSummary", "splitDiff", "splitDiffStep"]