"""Diff fetching for the review pipeline.

This module owns the shell-side diff production: it runs ``git fetch`` and
``git diff`` inside a sandbox and writes the unified diff to a known path so
agents can read it on demand via the ``get_diff`` tool. The in-sandbox split
step (:mod:`app.services.review.steps.split_diff`) then turns ``file.diff``
into the per-file annotated chunks and the line-set summary.
"""

from __future__ import annotations

import logging

from app.core.sandbox import BaseSandbox
from app.services.review.errors import DiffUnavailableError
from app.services.review.helpers import get_review_diff_dir_path

log = logging.getLogger(__name__)


def truncate_diff_output(raw: str, *, max_chars: int = 500) -> str:
    """Trim a command's stderr/stdout tail for inclusion in an error."""
    cleaned = (raw or "").strip()
    return cleaned[:max_chars]


async def fetch_diff(
    *,
    sandbox: BaseSandbox,
    repo_id: str,
    repo_path_str: str,
    pr_number: int,
    base_sha: str,
    head_sha: str,
) -> str:
    """Fetch the unified diff and write it to the sandbox.

    The diff is persisted at ``/home/user/tmp/{pr_number}/{head_sha}/file.diff``
    so the review agent can read it via the ``get_diff`` tool. The function
    returns the sandbox path of the saved diff on success.

    Raises:
        DiffUnavailableError: when ``mkdir``, ``git diff`` or any
            sub-command returns a non-zero exit code. The cause carries
            the truncated stderr / stdout tail.
    """
    diff_dir = get_review_diff_dir_path(pr_number, head_sha)
    diff_file = f"{diff_dir}/file.diff"

    mkdir_result = await sandbox.execute(
        f"mkdir -p {diff_dir}",
        cwd=repo_path_str,
        timeout=30,
    )
    if mkdir_result.exit_code != 0:
        raise DiffUnavailableError(
            repo_id=repo_id,
            base_sha=base_sha,
            head_sha=head_sha,
            cause=f"mkdir -p failed: {truncate_diff_output(mkdir_result.stderr)}",
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
    if diff_result.exit_code != 0:
        tail = truncate_diff_output(diff_result.stderr or diff_result.stdout or "")
        raise DiffUnavailableError(
            repo_id=repo_id,
            base_sha=base_sha,
            head_sha=head_sha,
            cause=f"git diff exited {diff_result.exit_code}: {tail}",
        )

    log.info(
        "Saved PR diff to sandbox: pr_number=%s path=%s",
        pr_number,
        diff_file,
    )
    return diff_file


__all__ = [
    "fetch_diff",
    "truncate_diff_output",
]
