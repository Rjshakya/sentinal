"""Dev helper: run ``split_diff.py`` against a diff and verify its output.

Usage: ``python test_split.py <file.diff> [out_dir]``

- Reads ``<file.diff>`` (default: ``dataset/test.diff``).
- Wipes and recreates ``out_dir`` (default: ``dataset/splitted_diff/``).
- Runs ``services/review/scripts/split_diff.py`` via a subprocess
  (the same CLI contract the host step consumes), passing
  ``--pr 42 --commit abc1234`` so the overview header is exercised.
- Parses stdout with the *shared* parser
  :func:`app.services.review.helpers.parse_split_summary` — the exact
  code the host step uses — so the two never drift.
- Asserts:
  - ``files_changed`` + ``len(skipped)`` equals the number of
    ``diff --git`` sections (every section becomes a chunk or is skipped)
  - every changed file has its ``.md`` chunk created flat under
    ``out_dir/splitted_diffs/``
  - every ``skipped`` file has no chunk on disk
  - ``out_dir/overview.md`` exists with the PR/commit header and the
    four bucket section headers
- Prints a concise 3-line summary for eyeballing.

No golden-file comparison — this is a sanity check for manual review.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

_DATASET_DIR = Path(__file__).resolve().parent
_DIFF_PATH = _DATASET_DIR / "test.diff"
_OUT_DIR = _DATASET_DIR / "splitted_diff"
_SRC_DIR = _DATASET_DIR.parent / "src"
_SPLIT_SCRIPT = (
    _DATASET_DIR.parent
    / "src"
    / "app"
    / "services"
    / "review"
    / "scripts"
    / "split_diff.py"
)
_OVERVIEW_HEADERS = (
    "## Files Added",
    "## Files Removed",
    "## Files Modified",
    "## Files Renamed",
)

sys.path.insert(0, str(_SRC_DIR))
from app.services.review.helpers import parse_split_summary


def count_diff_sections(diff_text: str) -> int:
    """Count ``diff --git`` section headers in the raw diff."""
    return sum(1 for line in diff_text.splitlines() if line.startswith("diff --git "))


def main() -> int:

    parser = argparse.ArgumentParser(description="test diff splitting")
    parser.add_argument("diff_path", help="path of diff", default=_DIFF_PATH)
    parser.add_argument("out_dir", help="out dir", default=_OUT_DIR)

    args = parser.parse_args()

    diff_path = Path(args.diff_path)
    out_dir = Path(args.out_dir)

    if not diff_path.exists():
        print(f"diff missing: {diff_path}", file=sys.stderr)
        return 1
    if not _SPLIT_SCRIPT.exists():
        print(f"split script missing: {_SPLIT_SCRIPT}", file=sys.stderr)
        return 1

    if not out_dir.exists():
        out_dir.mkdir(parents=True)

    diff_text = diff_path.read_text(encoding="utf-8", errors="ignore")
    expected_files = count_diff_sections(diff_text)

    result = subprocess.run(
        [
            sys.executable,
            str(_SPLIT_SCRIPT),
            str(diff_path),
            str(out_dir),
            "--pr",
            "45",
            "--commit",
            "abc12346",
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"split_diff.py exited {result.returncode}", file=sys.stderr)
        print(result.stderr, file=sys.stderr)
        return 1

    summary = parse_split_summary(result.stdout)

    if summary["files_changed"] + len(summary["skipped"]) != expected_files:
        print(
            f"files_changed + skipped={summary['files_changed'] + len(summary['skipped'])} "
            f"!= diff sections={expected_files}",
            file=sys.stderr,
        )
        return 1

    chunks_dir = out_dir / "splitted_diffs"
    chunk_files = list(chunks_dir.glob("*.md"))
    nested = [p for p in chunks_dir.rglob("*") if p.is_dir()]
    if nested:
        print("unexpected subdirectories:", *nested, sep="\n  ", file=sys.stderr)
        return 1
    if len(chunk_files) != summary["files_changed"]:
        print(
            f"chunks on disk={len(chunk_files)} != files_changed={summary['files_changed']}",
            file=sys.stderr,
        )
        return 1

    for name in summary["skipped"]:
        chunk_path = chunks_dir / (name.replace("/", ".") + ".md")
        if chunk_path.exists():
            print(f"skipped file has a chunk: {chunk_path}", file=sys.stderr)
            return 1

    overview = out_dir / "overview.md"
    if not summary["overview_written"]:
        print("summary says overview.md was not written", file=sys.stderr)
        return 1
    if not overview.exists():
        print(f"overview missing: {overview}", file=sys.stderr)
        return 1
    overview_text = overview.read_text(encoding="utf-8")
    if "PR #45 — commit abc12346" not in overview_text:
        print("overview header missing (PR #45 — commit abc12346)", file=sys.stderr)
        return 1
    missing_headers = [h for h in _OVERVIEW_HEADERS if h not in overview_text]
    if missing_headers:
        print(
            "missing overview headers:", *missing_headers, sep="\n  ", file=sys.stderr
        )
        return 1

    print(f"overview.md: {'created' if overview.exists() else 'MISSING'}")
    print(f"splitted_diffs/: {summary['files_changed']} files")
    if summary["skipped"]:
        print("skipped:")
        for name in summary["skipped"]:
            print(f"  {name}")
    else:
        print("skipped: none")
    return 0


if __name__ == "__main__":
    sys.exit(main())
