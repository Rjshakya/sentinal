"""Split a unified PR diff into per-file annotated chunks.

In-sandbox script: the host uploads this file as bytes and executes it
inside the sandbox (``python3 split_diff.py <file.diff> <dir>``). It is
never imported on the host, so it is fully self-contained (stdlib only,
no ``app.*`` imports).

Layout — given the sandbox dir ``p = /home/user/tmp/{pr}/{commit}``
(where ``p/file.diff`` already lives, written by the fetch step)::

    p/
    ├── file.diff            raw diff (read-only input)
    ├── overview.md          high-level "what changed" document
    └── splitted_diffs/      per-file annotated chunks (flat, dotted names)
        ├── src.app.auth.session.py.md
        └── ...

1. Reads ``<file.diff>`` (the unified diff from ``git diff base...head``).
2. Splits it into per-file sections (``diff --git a/.. b/..`` boundaries)
   and buckets each into Added / Removed / Modified / Renamed by its
   section markers (``new file mode`` / ``deleted file mode`` /
   ``similarity index``).
3. Writes ``<dir>/overview.md`` — the four buckets, paths only (renames
   render ``old → new``, binaries get a ``(binary)`` note), separated by
   ``---``. This is the agent's gate: a tiny "what changed" map with
   zero content.
4. For every changed file with hunks, writes
   ``<dir>/splitted_diffs/<file_name>.md`` — the diff annotated with
   per-side gutter line numbers. The on-disk file name flattens the
   path with ``.`` (``src/app/a.py`` → ``src.app.a.py.md``); the
   ``### {real path}`` header inside the chunk keeps the real path.

   Chunk shape::

    ### src/app/auth/session.py

    ```diff

    @@ -20,19 +20,19 @@ def create_session(user_id: str) -> Session:
      20   20   def create_session(user_id: str) -> Session:
      22       -  token = generate_token(user_id)
            22   +  token = generate_token(user_id, ttl=SESSION_TTL_SECONDS)
      23   24     return Session(token=token, user_id=user_id)

    ```

   The two gutter columns are the LEFT (old) and RIGHT (new) line
   numbers. Context lines show both; removed lines blank the right
   column; added lines blank the left. The ``@@`` hunk headers are
   kept verbatim; the git ``\\ No newline at end of file`` marker is
   passed through unguttered.
5. Prints one compact JSON line to stdout — the per-file line sets
   (``ParsedDiff`` shape) the host uses as the comment-anchor backstop
   and for lane grouping. The diff text itself never crosses the
   sandbox boundary.

Skipped from chunks (no ``.md``, no JSON entry): binary files and
files with no hunks (pure renames) — they still appear in the overview.

Usage: ``split_diff.py <file.diff> <dir> [--pr <number>] [--commit <sha>]``
"""

from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import asdict, dataclass, field
from typing import Literal

_HUNK_HEADER_RE = re.compile(
    r"^@@ -(?P<old>\d+)(?:,(?P<old_n>\d+))? "
    r"\+(?P<new>\d+)(?:,(?P<new_n>\d+))? @@"
)
_NO_NEWLINE_MARKER = "\\ No newline at end of file"
_BINARY_PREFIX = "Binary files "
_GUTTER = 5

SectionKind = Literal["added", "removed", "modified", "renamed"]

_SECTION_TITLES: tuple[tuple[SectionKind, str], ...] = (
    ("added", "Files Added"),
    ("removed", "Files Removed"),
    ("modified", "Files Modified"),
    ("renamed", "Files Renamed"),
)


@dataclass
class Section:
    """One ``diff --git`` section: the new path and its raw lines."""

    name: str
    body: list[str]


@dataclass
class AnnotatedFile:
    """A section after annotation: rendered body plus per-side line sets."""

    name: str
    body: list[str]
    right: set[int] = field(default_factory=set)
    left: set[int] = field(default_factory=set)


@dataclass
class FileEntry:
    """Per-file line sets in the host summary.

    Field names are uppercase because they ARE the wire format: the
    host ``ParsedDiff`` contract expects exactly ``RIGHT`` / ``LEFT``.
    """

    RIGHT: list[int]
    LEFT: list[int]


@dataclass
class Summary:
    """The compact summary printed to stdout (``ParsedDiff`` shape)."""

    files: dict[str, FileEntry]
    files_changed: int
    right_lines_total: int
    left_lines_total: int


def split_sections(diff_text: str) -> list[Section]:
    """Split the diff into per-file sections on ``diff --git`` headers.

    A section starts at a ``diff --git a/<a> b/<b>`` line; its name is
    the ``b/`` side (the new path), which is the name the agent should
    anchor comments against.
    """
    sections: list[Section] = []
    current: Section | None = None

    for line in diff_text.splitlines():
        if line.startswith("diff --git "):
            match = re.match(r"^diff --git a/.+? b/(?P<b>.+)$", line)
            name = match.group("b") if match is not None else None
            if name is not None:
                current = Section(name=name, body=[])
                sections.append(current)
            else:
                current = None
            continue
        if current is not None:
            current.body.append(line)

    return sections


def classify_section(section: Section) -> SectionKind:
    """Classify a section into its overview bucket from git's markers."""
    for line in section.body:
        if line.startswith("new file mode"):
            return "added"
        if line.startswith("deleted file mode"):
            return "removed"
        if line.startswith("similarity index"):
            return "renamed"
    return "modified"


def rename_old_path(section: Section) -> str | None:
    """Old path of a renamed section (bare path, no ``a/`` prefix)."""
    for line in section.body:
        if line.startswith("rename from "):
            return line[len("rename from ") :]
    return None


def is_binary_section(section: Section) -> bool:
    """True when the section carries a ``Binary files ...`` line."""
    return any(line.startswith(_BINARY_PREFIX) for line in section.body)


def bucket_entry(name: str, old: str | None, binary: bool) -> str:
    """One overview entry line: ``name``, ``old → name``, or ``name (binary)``."""
    if binary:
        return f"{name} (binary)"
    if old is not None:
        return f"{old} → {name}"
    return name


def build_overview(
    buckets: dict[SectionKind, list[str]], pr: str | None, commit: str | None
) -> str:
    """Build the overview document from the four path buckets."""
    if pr is not None and commit is not None:
        header = f"PR #{pr} — commit {commit}"
    elif pr is not None:
        header = f"PR #{pr}"
    elif commit is not None:
        header = f"commit {commit}"
    else:
        header = "—"

    parts: list[str] = ["# Diff overview", "", header, ""]
    for kind, title in _SECTION_TITLES:
        parts.append(f"## {title}")
        parts.append("")
        parts.append("---")
        parts.append("")
        for entry in buckets[kind]:
            parts.append(entry)

        parts.append("")
        parts.append("---")
        parts.append("")
    return "\n".join(parts)


def _render(old: int | None, new: int | None, line: str) -> str:
    """Render one diff line with the two gutter columns."""
    old_s = f"{old:>{_GUTTER}}" if old is not None else " " * _GUTTER
    new_s = f"{new:>{_GUTTER}}" if new is not None else " " * _GUTTER
    return f"{old_s} {new_s} {line}"


def annotate_section(section: Section) -> AnnotatedFile | None:
    """Walk one file section; annotate lines and collect line sets.

    Returns the annotated file, or ``None`` when the section is binary
    or has no hunks (rename-only).

    Cursors are driven by the body markers (``+`` / ``-`` / `` ``),
    initialised from each ``@@`` header's start numbers.
    """
    if is_binary_section(section):
        return None

    annotated: list[str] = []
    right_lines: set[int] = set()
    left_lines: set[int] = set()
    left_cursor: int | None = None
    right_cursor: int | None = None

    for line in section.body:
        header = _HUNK_HEADER_RE.match(line)
        if header is not None:
            old_start = header.group("old")
            new_start = header.group("new")
            if old_start is None or new_start is None:
                annotated.append(line)
                continue
            left_cursor = int(old_start)
            right_cursor = int(new_start)
            annotated.append(line)
            continue

        if line.startswith(("--- ", "+++ ", "diff --git ")) or line == _NO_NEWLINE_MARKER:
            annotated.append(line)
            continue

        if not line:
            annotated.append("")
            continue

        marker = line[0]
        if marker == "+" and right_cursor is not None:
            right_cursor += 1
            right_lines.add(right_cursor)
            annotated.append(_render(None, right_cursor, line))
        elif marker == "-" and left_cursor is not None:
            left_cursor += 1
            left_lines.add(left_cursor)
            annotated.append(_render(left_cursor, None, line))
        elif marker == " " and left_cursor is not None and right_cursor is not None:
            left_cursor += 1
            right_cursor += 1
            left_lines.add(left_cursor)
            right_lines.add(right_cursor)
            annotated.append(_render(left_cursor, right_cursor, line))
        else:
            annotated.append(line)

    if not right_lines and not left_lines:
        return None

    return AnnotatedFile(
        name=section.name,
        body=annotated,
        right=right_lines,
        left=left_lines,
    )


def render_chunk(name: str, body: list[str]) -> str:
    """Wrap an annotated body in the markdown chunk shape."""
    return f"### {name}\n\n```diff\n\n" + "\n".join(body) + "\n\n```\n"


def build_summary(files: list[AnnotatedFile]) -> Summary:
    """Build the compact host summary (``ParsedDiff`` shape)."""
    summary_files: dict[str, FileEntry] = {
        f.name: FileEntry(RIGHT=sorted(f.right), LEFT=sorted(f.left))
        for f in files
    }
    return Summary(
        files=summary_files,
        files_changed=len(files),
        right_lines_total=sum(len(f.right) for f in files),
        left_lines_total=sum(len(f.left) for f in files),
    )


def main(argv: list[str]) -> int:
    positional: list[str] = []
    pr: str | None = None
    commit: str | None = None

    i = 1
    while i < len(argv):
        arg = argv[i]
        if arg == "--pr":
            i += 1
            if i >= len(argv):
                print("usage: --pr <number>", file=sys.stderr)
                return 2
            pr = argv[i]
        elif arg == "--commit":
            i += 1
            if i >= len(argv):
                print("usage: --commit <sha>", file=sys.stderr)
                return 2
            commit = argv[i]
        else:
            positional.append(arg)
        i += 1

    if len(positional) != 2:
        print(
            f"usage: {argv[0]} <file.diff> <dir> [--pr <number>] [--commit <sha>]",
            file=sys.stderr,
        )
        return 2

    diff_path, out_dir = positional

    try:
        with open(diff_path, "r", encoding="utf-8", errors="ignore") as fh:
            diff_text = fh.read()
    except OSError as exc:
        print(f"failed to read diff: {exc}", file=sys.stderr)
        return 1

    chunks_dir = os.path.join(out_dir, "splitted_diffs")
    os.makedirs(chunks_dir, exist_ok=True)

    buckets: dict[SectionKind, list[str]] = {
        "added": [],
        "removed": [],
        "modified": [],
        "renamed": [],
    }
    annotated: list[AnnotatedFile] = []

    for section in split_sections(diff_text):
        kind = classify_section(section)
        old = rename_old_path(section) if kind == "renamed" else None
        buckets[kind].append(
            bucket_entry(section.name, old, is_binary_section(section))
        )

        result = annotate_section(section)
        if result is None:
            continue
        chunk_path = os.path.join(chunks_dir, result.name.replace("/", ".") + ".md")
        with open(chunk_path, "w", encoding="utf-8") as fh:
            fh.write(render_chunk(result.name, result.body))
        annotated.append(result)

    overview_path = os.path.join(out_dir, "overview.md")
    with open(overview_path, "w", encoding="utf-8") as fh:
        fh.write(build_overview(buckets, pr, commit))

    print(json.dumps(asdict(build_summary(annotated))))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
