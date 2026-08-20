"""Dev helper: run ``split_diff.py`` against a diff and verify its output.

Usage: ``python test_split.py <file.diff> [out_dir]``

- Reads ``<file.diff>`` (default: ``dataset/test.diff``).
- Wipes and recreates ``out_dir`` (default: ``dataset/splitted_diff/``).
- Runs ``services/review/scripts/split_diff.py`` via a subprocess
  (the same CLI contract the future host step consumes), passing
  ``--pr 42 --commit abc1234`` so the overview header is exercised.
- Asserts:
  - every file in the printed summary has its ``.md`` chunk created
    flat under ``out_dir/splitted_diffs/``
  - ``out_dir/overview.md`` exists with the PR/commit header and the
    four bucket section headers
- Prints the run summary for eyeballing.

No golden-file comparison — this is a sanity check for manual review.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

_DATASET_DIR = Path(__file__).resolve().parent
_DIFF_PATH = _DATASET_DIR / "test.diff"
_OUT_DIR = _DATASET_DIR / "splitted_diff"
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


def count_diff_sections(diff_text: str) -> int:
    """Count ``diff --git`` section headers in the raw diff."""
    return sum(1 for line in diff_text.splitlines() if line.startswith("diff --git "))


def main(argv: list[str]) -> int:
    diff_path = Path(argv[1]) if len(argv) > 1 else _DIFF_PATH
    out_dir = Path(argv[2]) if len(argv) > 2 else _OUT_DIR

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
            "42",
            "--commit",
            "abc1234",
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"split_diff.py exited {result.returncode}", file=sys.stderr)
        print(result.stderr, file=sys.stderr)
        return 1

    try:
        summary = json.loads(result.stdout.strip())
    except json.JSONDecodeError as exc:
        print(f"stdout is not valid JSON: {exc}", file=sys.stderr)
        return 1

    files = summary["files"]
    assert summary["files_changed"] == expected_files, (
        f"files_changed={summary['files_changed']} != diff sections={expected_files}"
    )

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

    overview = out_dir / "overview.md"
    if not overview.exists():
        print(f"overview missing: {overview}", file=sys.stderr)
        return 1
    overview_text = overview.read_text(encoding="utf-8")
    if "PR #42 — commit abc1234" not in overview_text:
        print("overview header missing (PR #42 — commit abc1234)", file=sys.stderr)
        return 1
    missing_headers = [h for h in _OVERVIEW_HEADERS if h not in overview_text]
    if missing_headers:
        print("missing overview headers:", *missing_headers, sep="\n  ", file=sys.stderr)
        return 1

    print(
        f"ok: {summary['files_changed']} files, "
        f"{summary['right_lines_total']} right lines, "
        f"{summary['left_lines_total']} left lines"
    )
    print(f"overview: {overview}")
    for name in files:
        entry = files[name]
        print(
            f"  {name}: RIGHT={len(entry['RIGHT'])} LEFT={len(entry['LEFT'])}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))