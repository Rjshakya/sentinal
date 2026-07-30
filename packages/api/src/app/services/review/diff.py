"""Diff fetching and classification for the review pipeline.

This module owns the shell-side diff production: it runs ``git fetch`` and
``git diff`` inside a sandbox and writes the unified diff to a known path so
agents can read it on demand via the ``get_diff`` tool.

After the diff is written, :func:`parse_and_write_diff_json` reads the
diff back, parses it into a structured :data:`HunkMap` (see
:mod:`app.services.review.hunk_map`), and writes a parallel
``diff.json`` so the review agent can call ``read_file`` on it directly.
"""

from __future__ import annotations

import logging

from app.core.sandbox import BaseSandbox
from app.services.review.errors import DiffUnavailableError
from app.services.review.hunk_map import (
    ParsedDiff,
    parse_hunk_map_to_json,
    serialise_hunk_map,
)

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
    diff_dir = f"/home/user/tmp/{pr_number}/{head_sha}"
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


async def parse_and_write_diff_json(
    sandbox: BaseSandbox,
    *,
    pr_number: int,
    head_sha: str,
    repo_id: str,
    base_sha: str,
) -> ParsedDiff:
    """Read ``file.diff`` from the sandbox, parse it, write ``diff.json``.

    The JSON file is written to the same directory as ``file.diff``:

    ```
    /home/user/tmp/{pr_number}/{head_sha}/
    ├── file.diff
    └── diff.json
    ```

    The returned :data:`ParsedDiff` is the same data structure that
    was written to the file. The caller can use it directly (without
    re-reading the sandbox) to build the in-memory :data:`HunkMap`
    that the workflow passes into
    :func:`app.services.review.hunk_map.filter_drafts` (the
    server-side backstop). The agent reads ``diff.json`` from the
    sandbox on its own via the deepagents backend's ``read_file``
    tool to self-validate and re-anchor its ``(file, line, side)``
    anchors.

    Raises:
        DiffUnavailableError: when ``file.diff`` is missing, empty, or
            cannot be read. The cause carries the truncated error text.
    """
    diff_dir = f"/home/user/tmp/{pr_number}/{head_sha}"
    diff_file = f"{diff_dir}/file.diff"
    json_file = f"{diff_dir}/diff.json"

    try:
        raw = await sandbox.read_text(diff_file)
    except FileNotFoundError as exc:
        raise DiffUnavailableError(
            repo_id=repo_id,
            base_sha=base_sha,
            head_sha=head_sha,
            cause=f"file.diff not found at {diff_file!r}: {exc}",
        ) from exc
    except Exception as exc:
        raise DiffUnavailableError(
            repo_id=repo_id,
            base_sha=base_sha,
            head_sha=head_sha,
            cause=f"failed to read {diff_file!r}: {type(exc).__name__}: {exc}",
        ) from exc

    if not raw or not raw.strip():
        raise DiffUnavailableError(
            repo_id=repo_id,
            base_sha=base_sha,
            head_sha=head_sha,
            cause=f"file.diff is empty at {diff_file!r}",
        )

    parsed = parse_hunk_map_to_json(raw)
    payload = serialise_hunk_map(parsed)

    try:
        await sandbox.write_text(json_file, payload)
    except Exception as exc:
        raise DiffUnavailableError(
            repo_id=repo_id,
            base_sha=base_sha,
            head_sha=head_sha,
            cause=f"failed to write {json_file!r}: {type(exc).__name__}: {exc}",
        ) from exc

    log.info(
        "Saved PR diff json to sandbox: pr_number=%s path=%s "
        "files_changed=%d right_lines_total=%d left_lines_total=%d",
        pr_number,
        json_file,
        parsed["summary"]["files_changed"],
        parsed["summary"]["right_lines_total"],
        parsed["summary"]["left_lines_total"],
    )
    return parsed


__all__ = [
    "fetch_diff",
    "parse_and_write_diff_json",
    "truncate_diff_output",
]
