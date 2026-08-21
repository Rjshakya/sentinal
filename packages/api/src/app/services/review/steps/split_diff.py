"""DBOS durable step: split the fetched diff into per-file chunks.

Connects to the E2B sandbox, uploads the in-sandbox
:file:`scripts/split_diff.py` (read as bytes on the host), and runs it
against ``file.diff``. The script writes ``overview.md`` and the
per-file annotated chunks under ``splitted_diffs/`` next to the diff,
and prints one compact JSON line to stdout — the tiny split summary
(``overview_written`` / ``files_changed`` / ``skipped``) parsed by the
shared :func:`app.services.review.helpers.parse_split_summary`.

Mirrors :func:`app.services.review.steps.fetch_diff.fetch_diff_step`:
reconnect by id, do the work, stop the sandbox in a ``finally`` so a
split failure does not leak the connection.

Exit-code contract (mirrors the indexing pipeline): ``0`` success
(stdout is the summary JSON), ``-1`` transient runner dropout
(retried), ``>0`` script failure (business outcome — the diff cannot
be split).
"""

from __future__ import annotations

import logging
from pathlib import Path

from dbos import DBOS

from app.core.sandbox import BaseSandbox
from app.core.sandbox.e2b import E2BSandbox
from app.services.review._internal import _SHOULD_RETRY_TRANSIENT, _e2b_spec
from app.services.review.diff import truncate_diff_output
from app.services.review.errors import (
    DiffSplitError,
    DiffSplitSetupError,
    SandboxConnectError,
)
from app.services.review.helpers import (
    SplitDiffResult,
    get_review_diff_dir_path,
    parse_split_summary,
)

log = logging.getLogger(__name__)

_SCRIPTS_DIR: Path = Path(__file__).resolve().parent.parent / "scripts"
"""Directory holding the in-sandbox scripts; the host reads them as bytes."""
_SCRIPT_REMOTE_PATH = "/home/user/split_diff.py"
"""Where the split script lands inside the sandbox."""
_RUN_TIMEOUT_S = 60


async def _run_split_diff(
    *,
    sandbox: BaseSandbox,
    repo_id: str,
    pr_number: int,
    head_sha: str,
) -> SplitDiffResult:
    """Upload the split script and run it against ``file.diff``."""
    diff_dir = get_review_diff_dir_path(pr_number, head_sha)
    diff_file = f"{diff_dir}/file.diff"

    script_src = _SCRIPTS_DIR / "split_diff.py"
    try:
        await sandbox.fs_write(
            _SCRIPT_REMOTE_PATH, script_src.read_text(encoding="utf-8")
        )
    except Exception as exc:
        raise DiffSplitSetupError(
            repo_id=repo_id,
            pr_number=pr_number,
            head_sha=head_sha,
            cause=f"failed to upload split script: {type(exc).__name__}: {exc}",
        ) from exc

    try:
        result = await sandbox.execute(
            f"python3 {_SCRIPT_REMOTE_PATH} {diff_file} {diff_dir} "
            f"--pr {pr_number} --commit {head_sha}",
            cwd="/home/user",
            timeout=_RUN_TIMEOUT_S,
        )
    except Exception as exc:
        raise DiffSplitSetupError(
            repo_id=repo_id,
            pr_number=pr_number,
            head_sha=head_sha,
            cause=f"failed to run split script: {type(exc).__name__}: {exc}",
        ) from exc

    if result.exit_code == -1:
        raise DiffSplitSetupError(
            repo_id=repo_id,
            pr_number=pr_number,
            head_sha=head_sha,
            cause="runner dropped the split script (exit -1)",
        )
    if result.exit_code != 0:
        tail = truncate_diff_output(result.stderr or result.stdout or "")
        raise DiffSplitError(
            repo_id=repo_id,
            pr_number=pr_number,
            head_sha=head_sha,
            cause=f"split script exited {result.exit_code}: {tail}",
        )

    try:
        summary = parse_split_summary(result.stdout)
    except ValueError as exc:
        raise DiffSplitError(
            repo_id=repo_id,
            pr_number=pr_number,
            head_sha=head_sha,
            cause=f"split summary unparseable: {exc}",
        ) from exc

    log.info(
        "split diff into chunks: pr_number=%s dir=%s files_changed=%d skipped=%d",
        pr_number,
        diff_dir,
        summary["files_changed"],
        len(summary["skipped"]),
    )
    return summary


@DBOS.step(
    retries_allowed=True,
    max_attempts=3,
    should_retry=_SHOULD_RETRY_TRANSIENT,
)
async def split_diff_step(
    *,
    sandbox_id: str,
    sandbox_name: str,
    repo_id: str,
    user_id: str,
    pr_number: int,
    head_sha: str,
) -> SplitDiffResult:
    """Durable step: split ``file.diff`` into per-file chunks.

    The diff is expected at ``/home/user/tmp/{pr_number}/{head_sha}/file.diff``,
    the path written by :func:`app.services.review.steps.fetch_diff.fetch_diff_step`.
    On success the sandbox holds ``overview.md`` and the
    ``splitted_diffs/`` chunks; the returned :class:`SplitDiffResult`
    carries the tiny split summary (``overview_written`` /
    ``files_changed`` / ``skipped``) without the diff text.

    Raises:
        SandboxConnectError: reconnect to E2B failed.
            :class:`TransientStepError` — DBOS retries.
        DiffSplitSetupError: script upload or the runner dropped the
            run. :class:`TransientStepError` — DBOS retries.
        DiffSplitError: the script exited non-zero or printed no
            parseable summary. Business outcome — not retried.
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
            cause=f"failed to reconnect sandbox for diff split: {type(exc).__name__}: {exc}",
        ) from exc

    try:
        return await _run_split_diff(
            sandbox=sandbox,
            repo_id=repo_id,
            pr_number=pr_number,
            head_sha=head_sha,
        )
    finally:
        try:
            await sandbox.stop()
        except Exception:
            log.exception("failed to stop sandbox after diff split")


__all__ = ["SplitDiffResult", "parse_split_summary", "split_diff_step"]
