"""Split the fetched diff into per-file annotated chunks, in-sandbox.

Runs one self-contained stdlib script inline (``python3 -c`` — no
uploads, no host imports): it splits ``file.diff`` on
``diff --git`` headers, writes one chunk per file with a hunk body
into ``splitted_diffs/``, writes ``overview.md`` beside the diff, and
prints a single JSON summary line to stdout. Skipped sections
(binary, renames without hunks) are reported, not written. The host
parses only the summary line — diff text never crosses the boundary.
"""

from __future__ import annotations

import json
import shlex
from typing import Any

from app.services.sandbox.errors import SandboxProviderError
from app.services.sandbox.service import getProvider
from app.services.sandbox.types import BaseSandbox, SandboxCtx
from app.utils.branded import CommitId, PRNumber
from app.utils.sandbox_fs import getDiffDir, getDiffFile
from app.workflows.review_v3.errors import SplitError
from app.workflows.review_v3.types import SplitSummary

_RUN_TIMEOUT_S = 60
_ERROR_CHARS = 500

_SPLIT_SCRIPT: str = r'''"""Split file.diff into per-file chunks (in-sandbox, stdlib only)."""

import argparse
import json
import os
import re
import sys

_DIFF_RE = re.compile(r"^diff --git a/(.*?) b/(.*?)\s*$")
_PLUS_RE = re.compile(r"^\+\+\+ b/(.*?)\s*$")


def main() -> int:
    parser = argparse.ArgumentParser(description="split file.diff into chunks")
    parser.add_argument("diff_file")
    parser.add_argument("out_dir")
    parser.add_argument("--pr", required=True)
    parser.add_argument("--commit", required=True)
    args = parser.parse_args()

    try:
        with open(args.diff_file, encoding="utf-8", errors="replace") as handle:
            text = handle.read()
    except OSError as exc:
        print(f"split: cannot read diff: {exc}", file=sys.stderr)
        return 1

    chunks: list[tuple[str, list[str]]] = []
    current_label: str | None = None
    current_lines: list[str] = []
    for line in text.split("\n"):
        match = _DIFF_RE.match(line)
        if match is not None:
            if current_label is not None:
                chunks.append((current_label, current_lines))
            current_label = f"a/{match.group(1)} b/{match.group(2)}"
            current_lines = [line]
        elif current_label is not None:
            current_lines.append(line)
    if current_label is not None:
        chunks.append((current_label, current_lines))

    split_dir = os.path.join(args.out_dir, "splitted_diffs")
    try:
        os.makedirs(split_dir, exist_ok=True)
    except OSError as exc:
        print(f"split: cannot prep output: {exc}", file=sys.stderr)
        return 1

    files_changed = 0
    skipped: list[str] = []
    overview_rows: list[str] = []
    for index, (label, lines) in enumerate(chunks):
        body = "\n".join(lines)
        plus_match = _PLUS_RE.search(body)
        path = plus_match.group(1) if plus_match else ""
        if path in ("", "/dev/null"):
            skipped.append(label)
            continue
        if "Binary files " in body:
            skipped.append(label)
            continue
        if not any(line.startswith("@@") for line in lines):
            skipped.append(label)
            continue
        safe = path.replace("/", "__")
        name = f"{index:03d}__{safe}.diff"
        try:
            with open(os.path.join(split_dir, name), "w", encoding="utf-8") as handle:
                handle.write(body if body.endswith("\n") else body + "\n")
        except OSError as exc:
            print(f"split: cannot write chunk: {exc}", file=sys.stderr)
            return 1
        files_changed += 1
        added = sum(
            1 for line in lines if line.startswith("+") and not line.startswith("+++")
        )
        removed = sum(
            1 for line in lines if line.startswith("-") and not line.startswith("---")
        )
        overview_rows.append(f"- `{path}` (+{added}/-{removed})")

    overview = (
        f"# Diff overview\n\nPR #{args.pr} @ `{args.commit}`\n\n"
        f"Files changed: {files_changed}\n"
        f"Skipped: {len(skipped)}\n\n"
        + ("\n".join(overview_rows) + "\n" if overview_rows else "")
    )
    try:
        with open(
            os.path.join(args.out_dir, "overview.md"), "w", encoding="utf-8"
        ) as handle:
            handle.write(overview)
    except OSError as exc:
        print(f"split: cannot write overview: {exc}", file=sys.stderr)
        return 1

    print(
        json.dumps(
            {
                "overview_written": True,
                "files_changed": files_changed,
                "skipped": skipped,
            }
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
'''


def parseSplitSummary(stdout: str) -> SplitSummary | SplitError:
    """Validate the script's single stdout JSON line (pure)."""
    try:
        data: Any = json.loads(stdout.strip())
    except Exception as exc:
        return SplitError(
            message=f"split summary is not JSON: {type(exc).__name__}: {exc}"
        )
    if not isinstance(data, dict):
        return SplitError(message="split summary is not a JSON object")
    overview = data.get("overview_written")
    files = data.get("files_changed")
    skipped = data.get("skipped")
    if not isinstance(overview, bool):
        return SplitError(message="split summary has no boolean overview_written")
    if not isinstance(files, int) or isinstance(files, bool) or files < 0:
        return SplitError(message="split summary has no non-negative files_changed")
    if not isinstance(skipped, list) or not all(
        isinstance(item, str) for item in skipped
    ):
        return SplitError(message="split summary has no string-list skipped")
    return SplitSummary(
        overviewWritten=overview, filesChanged=files, skipped=skipped
    )


async def splitDiff(
    *,
    sandboxCtx: SandboxCtx,
    prNumber: PRNumber,
    headSha: CommitId,
) -> SplitSummary | SplitError:
    """Split ``file.diff`` into per-file chunks next to the diff."""
    try:
        provider = getProvider(sandboxCtx.providerId)
    except Exception as exc:
        return SplitError(
            message=f"unknown sandbox provider: {type(exc).__name__}: {exc}",
            retryable=True,
        )
    try:
        made = await provider(ctx=sandboxCtx).create()
    except Exception as exc:
        return SplitError(
            message=f"sandbox reconnect raised {type(exc).__name__}: {exc}",
            retryable=True,
        )
    if isinstance(made, SandboxProviderError):
        return SplitError(
            message=f"sandbox reconnect failed: {made.message}", retryable=True
        )
    backend: BaseSandbox = made

    sha = str(headSha)
    diffDir = getDiffDir(sha)
    command = (
        f"python3 -c {shlex.quote(_SPLIT_SCRIPT)} "
        f"{shlex.quote(getDiffFile(sha))} {shlex.quote(diffDir)} "
        f"--pr {int(prNumber)} --commit {shlex.quote(sha)}"
    )
    try:
        ran = await backend.aexecute(command, timeout=_RUN_TIMEOUT_S)
    except Exception as exc:
        return SplitError(
            message=f"split run raised {type(exc).__name__}: {exc}", retryable=True
        )
    if ran.exit_code in (-1, 124):
        return SplitError(
            message="split run: runner dropped the command", retryable=True
        )
    if ran.exit_code != 0:
        return SplitError(
            message=f"split script exited {ran.exit_code}: "
            f"{ran.output.strip()[-_ERROR_CHARS:]}"
        )
    return parseSplitSummary(ran.output)


__all__ = ["SplitSummary", "parseSplitSummary", "splitDiff"]
