"""Diff fetching and classification for the review pipeline.

This module owns the shell-side diff production: it runs ``git fetch`` and
``git diff`` inside a sandbox and writes the unified diff to a known path so
agents can read it on demand via the ``get_diff`` tool.
"""

from __future__ import annotations

import logging

from app.core.result import Err, Ok, Result
from app.core.sandbox import BaseSandbox
from app.services.review.errors import DiffUnavailable

log = logging.getLogger(__name__)


def truncate_diff_output(raw: str, *, max_chars: int = 500) -> str:
    """Trim a command's stderr/stdout tail for inclusion in an error."""
    cleaned = (raw or "").strip()
    return cleaned[:max_chars]


def classify_diff_exit_code(
    *, exit_code: int, output_tail: str
) -> Result[None, DiffUnavailable]:
    """Map a ``git diff`` exit code to ``Result[None, DiffUnavailable]``."""
    if exit_code == 0:
        return Ok(None)
    return Err(
        DiffUnavailable(
            repo_id="",
            base_sha="",
            head_sha="",
            cause=f"git diff exited {exit_code}: {output_tail}",
        )
    )


async def fetch_diff(
    *,
    sandbox: BaseSandbox,
    repo_id: str,
    repo_path_str: str,
    pr_number: int,
    base_sha: str,
    head_sha: str,
) -> Result[str, DiffUnavailable]:
    """Fetch the unified diff and write it to the sandbox.

    The diff is persisted at ``/home/user/tmp/{pr_number}/{head_sha}/file.diff``
    so the review agent can read it via the ``get_diff`` tool. The function
    returns the sandbox path of the saved diff on success.
    """
    diff_dir = f"/home/user/tmp/{pr_number}/{head_sha}"
    diff_file = f"{diff_dir}/file.diff"

    mkdir_result = await sandbox.execute(
        f"mkdir -p {diff_dir}",
        cwd=repo_path_str,
        timeout=30,
    )
    if mkdir_result.exit_code != 0:
        return Err(
            DiffUnavailable(
                repo_id=repo_id,
                base_sha=base_sha,
                head_sha=head_sha,
                cause=f"mkdir -p failed: {truncate_diff_output(mkdir_result.stderr)}",
            )
        )

    fetch = await sandbox.execute(
        "git fetch origin",
        cwd=repo_path_str,
        timeout=120,
    )
    if fetch.exit_code != 0:
        log.warning(
            "git fetch origin failed (continuing): pr_number=%s exit_code=%s stderr=%s",
            pr_number,
            fetch.exit_code,
            fetch.stderr,
        )

    diff_command = f"bash -c 'git diff {base_sha}...{head_sha} > {diff_file}'"
    diff_result = await sandbox.execute(
        diff_command,
        cwd=repo_path_str,
        timeout=120,
    )
    classification = classify_diff_exit_code(
        exit_code=diff_result.exit_code,
        output_tail=truncate_diff_output(
            diff_result.stderr or diff_result.stdout or ""
        ),
    )
    if isinstance(classification, Err):
        return Err(
            DiffUnavailable(
                repo_id=repo_id,
                base_sha=base_sha,
                head_sha=head_sha,
                cause=classification.error.cause,
            )
        )

    log.info(
        "Saved PR diff to sandbox: pr_number=%s path=%s",
        pr_number,
        diff_file,
    )
    return Ok(diff_file)


__all__: list[str] = [
    "classify_diff_exit_code",
    "fetch_diff",
    "truncate_diff_output",
]
