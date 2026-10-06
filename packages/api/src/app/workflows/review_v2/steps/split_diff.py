"""Split the fetched diff into per-file annotated chunks.

Connects to the sandbox, uploads the in-sandbox
:file:`scripts/split_diff.py` (read as bytes on the host), and runs it
against ``file.diff``. The script writes ``overview.md`` and the
per-file annotated chunks under ``splitted_diffs/`` next to the diff,
and prints one compact JSON line to stdout — the tiny split summary
parsed by :func:`parseSplitSummary`.

Exit-code contract: ``0`` success (stdout is the summary JSON), ``124``
(timeout) / ``-1`` (runner dropout) transient, and ``>0`` script
failure (business outcome — the diff cannot be split).
:func:`parseSplitSummary` is the pure stdout parser.
"""

from __future__ import annotations

import json
import logging
import shlex
from pathlib import Path

from app.services.sandbox.types import SandboxCtx
from app.utils.branded import CommitId, PRNumber, RepoId
from app.workflows.review_v2.errors import (
    DiffSplitError,
    DiffSplitSetupError,
    ReviewStepFailure,
    SandboxConnectError,
    TransientReviewStepFailure,
)
from app.workflows.review_v2.steps._helpers import (
    asAsyncSandbox,
    connectSandbox,
    getReviewDiffDirPath,
    truncateOutput,
)
from app.workflows.review_v2.types import SplitDiffResult

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


def splitSetupError(
    message: str, *, repoId: RepoId, prNumber: PRNumber, headSha: CommitId
) -> TransientReviewStepFailure:
    return TransientReviewStepFailure(
        DiffSplitSetupError(
            message=message,
            repoId=repoId,
            prNumber=prNumber,
            headSha=headSha,
        )
    )


async def splitDiffStep(
    *,
    sandboxCtx: SandboxCtx,
    repoId: RepoId,
    prNumber: PRNumber,
    headSha: CommitId,
) -> SplitDiffResult:
    """Split ``file.diff`` into per-file chunks.

    On success the sandbox holds ``overview.md`` and the
    ``splitted_diffs/`` chunks; the returned :class:`SplitDiffResult`
    carries the tiny split summary without the diff text.

    Raises:
        TransientReviewStepFailure: sandbox reconnect / script upload /
            runner dropout failed.
        ReviewStepFailure: the script exited non-zero or printed no
            parseable summary.
    """
    sandbox = await connectSandbox(sandboxCtx)
    if isinstance(sandbox, SandboxConnectError):
        raise TransientReviewStepFailure(sandbox)
    backend = asAsyncSandbox(sandbox)

    diffDir = getReviewDiffDirPath(prNumber, headSha)
    diffFile = f"{diffDir}/file.diff"

    script_src = _SCRIPTS_DIR / "split_diff.py"
    try:
        uploads = await backend.aupload_files(
            [(_SCRIPT_REMOTE_PATH, script_src.read_bytes())]
        )
        upload_error = next((u.error for u in uploads if u.error is not None), None)
        if upload_error is not None:
            raise splitSetupError(
                f"failed to upload split script: {upload_error}",
                repoId=repoId,
                prNumber=prNumber,
                headSha=headSha,
            )
    except TransientReviewStepFailure:
        raise
    except Exception as exc:
        raise splitSetupError(
            f"failed to upload split script: {type(exc).__name__}: {exc}",
            repoId=repoId,
            prNumber=prNumber,
            headSha=headSha,
        ) from exc

    try:
        result = await backend.aexecute(
            f"python3 {shlex.quote(_SCRIPT_REMOTE_PATH)} "
            f"{shlex.quote(diffFile)} {shlex.quote(diffDir)} "
            f"--pr {prNumber} --commit {headSha}",
            timeout=_RUN_TIMEOUT_S,
        )
    except Exception as exc:
        raise splitSetupError(
            f"failed to run split script: {type(exc).__name__}: {exc}",
            repoId=repoId,
            prNumber=prNumber,
            headSha=headSha,
        ) from exc

    if result.exit_code in (-1, 124):
        raise splitSetupError(
            f"runner dropped the split script (exit {result.exit_code})",
            repoId=repoId,
            prNumber=prNumber,
            headSha=headSha,
        )
    if result.exit_code != 0:
        tail = truncateOutput(result.output)
        raise ReviewStepFailure(
            DiffSplitError(
                message=f"split script exited {result.exit_code}: {tail}",
                repoId=repoId,
                prNumber=prNumber,
                headSha=headSha,
            )
        )

    try:
        summary = parseSplitSummary(result.output.strip())
    except ValueError as exc:
        raise ReviewStepFailure(
            DiffSplitError(
                message=f"split summary unparseable: {exc}",
                repoId=repoId,
                prNumber=prNumber,
                headSha=headSha,
            )
        ) from exc

    log.info(
        "split_diff_step: ok pr_number=%s files_changed=%d skipped=%d",
        prNumber,
        summary["files_changed"],
        len(summary["skipped"]),
    )
    return summary


__all__ = ["parseSplitSummary", "splitDiffStep"]