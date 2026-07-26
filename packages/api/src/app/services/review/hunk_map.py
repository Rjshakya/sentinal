"""Unified-diff hunk parser and comment-draft filter.

The review agent emits inline review comments anchored to ``(file, line, side)``.
GitHub's review-comments API only accepts anchors that appear in the
``RIGHT`` (new) or ``LEFT`` (old) side of the diff. Anchors outside the
diff are rejected with HTTP 422, and the entire review POST is rejected
atomically.

This module parses a unified diff into a ``hunk_map`` — a dict that maps
each file to the set of line numbers visible on the ``RIGHT`` and
``LEFT`` sides of the diff. The map is then used by:

- :func:`filter_drafts` — the server-side filter, called once in
  :func:`app.services.review.workflow.review_workflow` after the agent
  returns. Drops drafts whose anchor is not in the map.
- :func:`make_verify_comment_line_tool` — the ``verify_comment_line``
  tool exposed to the review agent, which lets the LLM self-validate
  before emitting a draft.

The parser is pure (no I/O) and deterministic. The same diff always
produces the same map. The algorithm walks the diff's line markers
(``+`` / ``-`` / `` ``) and advances per-side cursors that were
initialised from each ``@@`` hunk header. Header counts (``X,Y`` in
``@@ -X,Y +A,B @@``) are not used as the source of truth — they are
metadata for humans; the line numbers come from the markers. This makes
the parser robust to header/body mismatches and to whitespace-only
differences at end-of-file.
"""

from __future__ import annotations

import json
import logging
import re
from typing import TypedDict

from app.services.agent.models import CodeCommentDraft, ReviewResult

log = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Public types                                                                 #
# --------------------------------------------------------------------------- #


HunkMap = dict[str, dict[str, set[int]]]
"""File-name → ``{"RIGHT": set[int], "LEFT": set[int]}``."""


class HunkInfo(TypedDict):
    """Serializable description of one hunk in the diff."""

    file: str
    old_start: int
    old_count: int
    new_start: int
    new_count: int
    function_context: str


class FileEntry(TypedDict):
    """Per-file entry in :data:`ParsedDiff.files`."""

    RIGHT: list[int]
    LEFT: list[int]


class ParsedDiffSummary(TypedDict):
    """Top-level summary in :data:`ParsedDiff`."""

    files_changed: int
    right_lines_total: int
    left_lines_total: int


class ParsedDiff(TypedDict):
    """Shape of the JSON written to ``diff.json`` in the sandbox."""

    files: dict[str, FileEntry]
    hunks: list[HunkInfo]
    summary: ParsedDiffSummary


# --------------------------------------------------------------------------- #
# Regex                                                                        #
# --------------------------------------------------------------------------- #


# ``@@ -<old>[,<old_count>] +<new>[,<new_count>] @@``
# Anchored at start-of-line; the function-context after the second ``@@``
# is captured separately (and discarded by the parser, but preserved in
# :data:`HunkInfo.function_context`).
_HUNK_HEADER_RE = re.compile(
    r"^@@ -(?P<old_start>\d+)(?:,(?P<old_count>\d+))? "
    r"\+(?P<new_start>\d+)(?:,(?P<new_count>\d+))? @@"
    r"(?P<fn_context>.*)$"
)

_DIFF_GIT_HEADER_RE = re.compile(r"^diff --git a/(?P<a>.+?) b/(?P<b>.+?)$")
_NEW_FILE_HEADER_RE = re.compile(r"^\+\+\+ b/(?P<path>.+?)\s*$")
_OLD_FILE_HEADER_RE = re.compile(r"^--- a/(?P<path>.+?)\s*$")
_NO_NEWLINE_MARKER = "\\ No newline at end of file"
_BINARY_MARKER = "Binary files "


# --------------------------------------------------------------------------- #
# Parser                                                                       #
# --------------------------------------------------------------------------- #


def _file_name_from_headers(
    *,
    diff_git_match: re.Match[str] | None,
    plus_match: re.Match[str] | None,
    current_file: str | None,
) -> str | None:
    """Resolve the file name for the current diff section.

    Prefers the ``diff --git`` ``b/`` side, falls back to the ``+++ b/``
    header. Returns ``None`` if neither is present (so the parser
    continues to accumulate hunks under the previous file, which is
    what ``git diff`` does for non-git-style diffs).
    """
    if diff_git_match is not None:
        return diff_git_match.group("b")
    if plus_match is not None:
        return plus_match.group("path")
    return current_file


def _file_is_binary(line: str) -> bool:
    """True if the line announces a binary file change."""
    return line.startswith(_BINARY_MARKER)


def _parse_hunk_header(line: str) -> tuple[int, int, int, int, str] | None:
    """Parse a single ``@@`` line. Returns ``(old_start, old_count,
    new_start, new_count, fn_context)`` or ``None`` if the line isn't a
    hunk header.

    Per the unified-diff spec, a missing count means 1.
    """
    match = _HUNK_HEADER_RE.match(line)
    if match is None:
        return None
    old_start = int(match.group("old_start"))
    new_start = int(match.group("new_start"))
    old_count = int(match.group("old_count") or "1")
    new_count = int(match.group("new_count") or "1")
    fn_context = match.group("fn_context") or ""
    return old_start, old_count, new_start, new_count, fn_context


def _flush_hunk(
    *,
    file_name: str,
    hunk: _ActiveHunk,
    hunk_map: HunkMap,
    hunks_list: list[HunkInfo],
) -> None:
    """Record one finished hunk into the running ``hunk_map`` and the
    serialisable ``hunks_list``."""
    file_entry = hunk_map.setdefault(file_name, {"RIGHT": set(), "LEFT": set()})
    file_entry["RIGHT"].update(hunk["right_lines"])
    file_entry["LEFT"].update(hunk["left_lines"])
    hunks_list.append(
        HunkInfo(
            file=file_name,
            old_start=hunk["old_start"],
            old_count=hunk["old_count"],
            new_start=hunk["new_start"],
            new_count=hunk["new_count"],
            function_context=hunk["function_context"],
        )
    )


class _ActiveHunk(TypedDict):
    """In-progress hunk state, used while walking the diff body."""

    old_start: int
    old_count: int
    new_start: int
    new_count: int
    function_context: str
    left_cursor: int
    right_cursor: int
    left_lines: set[int]
    right_lines: set[int]


def parse_hunk_map(unified_diff: str) -> HunkMap:
    """Walk a unified diff and return the :data:`HunkMap`.

    The map is the in-memory representation used by
    :func:`filter_drafts` and :func:`make_verify_comment_line_tool`.

    Algorithm (line-marker walker):

    1. When a ``diff --git`` header or a ``+++ b/`` header is seen, the
       current file name is updated.
    2. When a ``@@`` header is seen, the previous hunk (if any) is
       flushed into the map and a new active hunk starts with cursors
       initialised to the header's ``old_start`` / ``new_start``.
    3. For each body line:
         - ``+`` advances the right cursor and adds the right cursor to
           the right set.
         - ``-`` advances the left cursor and adds the left cursor to
           the left set.
         - `` `` (context) advances both cursors and adds both to their
           respective sets.
         - ``\\ No newline at end of file`` is a no-op; cursors do not
           advance.
    4. The marker-driven cursor walk is the source of truth; the
       ``X,Y`` counts in the hunk header are not used to size the
       hunk.

    Binary files (``Binary files a/x and b/y differ``) contribute no
    lines to the map; the file name is therefore absent from the
    returned dict.
    """
    hunk_map: HunkMap = {}
    hunks_list: list[HunkInfo] = []  # populated for parity with json variant
    _ = hunks_list  # silence unused warning; populated via _flush_hunk

    current_file: str | None = None
    active: _ActiveHunk | None = None

    lines = unified_diff.splitlines()
    idx = 0
    while idx < len(lines):
        line = lines[idx]

        # --- file boundary --------------------------------------------- #
        diff_git_match = _DIFF_GIT_HEADER_RE.match(line)
        if diff_git_match is not None:
            if active is not None and current_file is not None:
                _flush_hunk(
                    file_name=current_file,
                    hunk=active,
                    hunk_map=hunk_map,
                    hunks_list=hunks_list,
                )
                active = None
            current_file = _file_name_from_headers(
                diff_git_match=diff_git_match,
                plus_match=None,
                current_file=current_file,
            )
            idx += 1
            continue

        if line.startswith("--- "):
            # ``--- a/<path>`` — only the path, not parsed further.
            idx += 1
            continue

        plus_match = _NEW_FILE_HEADER_RE.match(line)
        if plus_match is not None:
            if active is not None and current_file is not None:
                _flush_hunk(
                    file_name=current_file,
                    hunk=active,
                    hunk_map=hunk_map,
                    hunks_list=hunks_list,
                )
                active = None
            current_file = _file_name_from_headers(
                diff_git_match=None,
                plus_match=plus_match,
                current_file=current_file,
            )
            idx += 1
            continue

        # --- binary file ------------------------------------------------ #
        if _file_is_binary(line):
            if active is not None and current_file is not None:
                _flush_hunk(
                    file_name=current_file,
                    hunk=active,
                    hunk_map=hunk_map,
                    hunks_list=hunks_list,
                )
                active = None
            current_file = None
            idx += 1
            continue

        # --- hunk header ----------------------------------------------- #
        hunk_header = _parse_hunk_header(line)
        if hunk_header is not None:
            if active is not None and current_file is not None:
                _flush_hunk(
                    file_name=current_file,
                    hunk=active,
                    hunk_map=hunk_map,
                    hunks_list=hunks_list,
                )
            old_start, old_count, new_start, new_count, fn_context = hunk_header
            active = _ActiveHunk(
                old_start=old_start,
                old_count=old_count,
                new_start=new_start,
                new_count=new_count,
                function_context=fn_context.strip(),
                left_cursor=old_start,
                right_cursor=new_start,
                left_lines=set(),
                right_lines=set(),
            )
            idx += 1
            continue

        # --- hunk body ------------------------------------------------- #
        if active is None:
            idx += 1
            continue

        if line.startswith(_NO_NEWLINE_MARKER):
            idx += 1
            continue

        if not line:
            # Truly empty line in a hunk body: treat as context. Some
            # diffs (e.g. empty context lines) emit an empty string.
            active["left_lines"].add(active["left_cursor"])
            active["right_lines"].add(active["right_cursor"])
            active["left_cursor"] += 1
            active["right_cursor"] += 1
            idx += 1
            continue

        marker = line[0]
        if marker == "+":
            active["right_lines"].add(active["right_cursor"])
            active["right_cursor"] += 1
        elif marker == "-":
            active["left_lines"].add(active["left_cursor"])
            active["left_cursor"] += 1
        elif marker == " ":
            active["left_lines"].add(active["left_cursor"])
            active["right_lines"].add(active["right_cursor"])
            active["left_cursor"] += 1
            active["right_cursor"] += 1
        else:
            # Unrecognised marker; treat as end-of-hunk safety so we
            # don't drift the cursors. Move on.
            pass

        idx += 1

    # --- final flush --------------------------------------------------- #
    if active is not None and current_file is not None:
        _flush_hunk(
            file_name=current_file,
            hunk=active,
            hunk_map=hunk_map,
            hunks_list=hunks_list,
        )

    return hunk_map


# --------------------------------------------------------------------------- #
# JSON serialiser                                                              #
# --------------------------------------------------------------------------- #


def parse_hunk_map_to_json(unified_diff: str) -> ParsedDiff:
    """Parse the diff into the JSON shape written to ``diff.json``.

    Same as :func:`parse_hunk_map` but also returns the per-hunk
    metadata and a top-level summary. Sets are serialised as sorted
    lists because JSON has no set type.
    """
    hunk_map = parse_hunk_map(unified_diff)

    # Re-parse to also collect the hunk list. Cheap relative to the
    # full review; done with a thin re-walk so the public functions
    # stay composable.
    files: dict[str, FileEntry] = {}
    hunks_list: list[HunkInfo] = []

    current_file: str | None = None
    active: _ActiveHunk | None = None

    lines = unified_diff.splitlines()
    idx = 0
    while idx < len(lines):
        line = lines[idx]

        diff_git_match = _DIFF_GIT_HEADER_RE.match(line)
        if diff_git_match is not None:
            if active is not None and current_file is not None:
                _record_hunk(
                    file_name=current_file,
                    hunk=active,
                    files=files,
                    hunks_list=hunks_list,
                )
                active = None
            current_file = diff_git_match.group("b")
            idx += 1
            continue

        if line.startswith("--- "):
            idx += 1
            continue

        plus_match = _NEW_FILE_HEADER_RE.match(line)
        if plus_match is not None:
            if active is not None and current_file is not None:
                _record_hunk(
                    file_name=current_file,
                    hunk=active,
                    files=files,
                    hunks_list=hunks_list,
                )
                active = None
            current_file = plus_match.group("path")
            idx += 1
            continue

        if _file_is_binary(line):
            if active is not None and current_file is not None:
                _record_hunk(
                    file_name=current_file,
                    hunk=active,
                    files=files,
                    hunks_list=hunks_list,
                )
                active = None
            current_file = None
            idx += 1
            continue

        hunk_header = _parse_hunk_header(line)
        if hunk_header is not None:
            if active is not None and current_file is not None:
                _record_hunk(
                    file_name=current_file,
                    hunk=active,
                    files=files,
                    hunks_list=hunks_list,
                )
            old_start, old_count, new_start, new_count, fn_context = hunk_header
            active = _ActiveHunk(
                old_start=old_start,
                old_count=old_count,
                new_start=new_start,
                new_count=new_count,
                function_context=fn_context.strip(),
                left_cursor=old_start,
                right_cursor=new_start,
                left_lines=set(),
                right_lines=set(),
            )
            idx += 1
            continue

        if active is None:
            idx += 1
            continue

        if line.startswith(_NO_NEWLINE_MARKER):
            idx += 1
            continue

        if not line:
            active["left_lines"].add(active["left_cursor"])
            active["right_lines"].add(active["right_cursor"])
            active["left_cursor"] += 1
            active["right_cursor"] += 1
            idx += 1
            continue

        marker = line[0]
        if marker == "+":
            active["right_lines"].add(active["right_cursor"])
            active["right_cursor"] += 1
        elif marker == "-":
            active["left_lines"].add(active["left_cursor"])
            active["left_cursor"] += 1
        elif marker == " ":
            active["left_lines"].add(active["left_cursor"])
            active["right_lines"].add(active["right_cursor"])
            active["left_cursor"] += 1
            active["right_cursor"] += 1
        idx += 1

    if active is not None and current_file is not None:
        _record_hunk(
            file_name=current_file,
            hunk=active,
            files=files,
            hunks_list=hunks_list,
        )

    right_total = sum(len(f["RIGHT"]) for f in files.values())
    left_total = sum(len(f["LEFT"]) for f in files.values())

    return ParsedDiff(
        files=files,
        hunks=hunks_list,
        summary=ParsedDiffSummary(
            files_changed=len(files),
            right_lines_total=right_total,
            left_lines_total=left_total,
        ),
    )


def _record_hunk(
    *,
    file_name: str,
    hunk: _ActiveHunk,
    files: dict[str, FileEntry],
    hunks_list: list[HunkInfo],
) -> None:
    """Accumulate a finished hunk into the serialisable structures."""
    file_entry = files.setdefault(
        file_name,
        FileEntry(RIGHT=sorted(hunk["right_lines"]), LEFT=sorted(hunk["left_lines"])),
    )
    if hunk["right_lines"]:
        # Merge by re-sorting the union; the entry may already exist
        # from a previous hunk in the same file.
        merged_right = sorted(set(file_entry["RIGHT"]) | hunk["right_lines"])
        merged_left = sorted(set(file_entry["LEFT"]) | hunk["left_lines"])
        files[file_name] = FileEntry(RIGHT=merged_right, LEFT=merged_left)
    hunks_list.append(
        HunkInfo(
            file=file_name,
            old_start=hunk["old_start"],
            old_count=hunk["old_count"],
            new_start=hunk["new_start"],
            new_count=hunk["new_count"],
            function_context=hunk["function_context"],
        )
    )


def serialise_hunk_map(parsed: ParsedDiff) -> str:
    """Pretty-print a :data:`ParsedDiff` to a JSON string.

    Sets are already serialised as sorted lists by
    :func:`parse_hunk_map_to_json`, so this is a thin wrapper.
    """
    return json.dumps(parsed, indent=2, sort_keys=False)


# --------------------------------------------------------------------------- #
# Filter                                                                       #
# --------------------------------------------------------------------------- #


def filter_drafts(
    review: ReviewResult,
    hunk_map: HunkMap,
) -> ReviewResult:
    """Drop drafts whose anchor is not in the :data:`HunkMap`.

    A draft is kept iff:

    - ``file_name`` appears in ``hunk_map``, AND
    - ``side`` (``"RIGHT"`` / ``"LEFT"``) is a key in that file's
      entry, AND
    - ``from_line`` is in the corresponding set.

    ``summary`` and ``verdict`` pass through unchanged. Only the
    ``comments`` field is replaced.

    Drops are recorded as a structured log line
    ``review_comments_filtered`` with the dropped tuples
    ``[(draft, reason), ...]``. Reasons are one of:

    - ``"file_not_in_diff"`` — ``file_name`` is not a key in the map.
    - ``"side_invalid"`` — ``side`` is neither ``"RIGHT"`` nor
      ``"LEFT"`` (shouldn't happen for a validated draft, but
      defended against).
    - ``"line_not_in_range"`` — ``(file, side)`` is in the map but
      ``from_line`` is not in the set.
    """
    kept: list[CodeCommentDraft] = []
    dropped: list[tuple[CodeCommentDraft, str]] = []

    for draft in review.comments:
        file_entry = hunk_map.get(draft.file_name)
        if file_entry is None:
            dropped.append((draft, "file_not_in_diff"))
            continue

        side_set = file_entry.get(draft.side)
        if side_set is None:
            dropped.append((draft, "side_invalid"))
            continue

        if draft.from_line not in side_set:
            dropped.append((draft, "line_not_in_range"))
            continue

        kept.append(draft)

    if dropped:
        log.warning(
            "review_comments_filtered: total=%d dropped=%d kept=%d",
            len(review.comments),
            len(dropped),
            len(kept),
        )
        for draft, reason in dropped:
            log.warning(
                "review_comments_filtered_item: file=%s line=%d side=%s reason=%s",
                draft.file_name,
                draft.from_line,
                draft.side,
                reason,
            )

    return review.model_copy(update={"comments": kept})


__all__ = [
    "FileEntry",
    "HunkInfo",
    "HunkMap",
    "ParsedDiff",
    "ParsedDiffSummary",
    "filter_drafts",
    "parse_hunk_map",
    "parse_hunk_map_to_json",
    "serialise_hunk_map",
]
