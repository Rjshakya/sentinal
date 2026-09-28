# review_v2/scripts — files executed inside the sandbox

In-sandbox programs, uploaded as bytes and run there — never
imported on the host. Stdlib-only so they run on a bare image
without installs.

## Layout

- `split_diff.py` — per-file diff splitter. Usage:
  `split_diff.py <file.diff> <out_dir>`. Writes `overview.md`
  (paths-only gate document) plus one annotated chunk per file
  into `splitted_diffs/`, and prints the tiny `SplitDiffResult`
  summary JSON (`overview_written`, `files_changed`, `skipped`)
  to stdout. Exit codes: `0` success, `-1` transient runner
  dropout, `>0` final `DiffSplitError`.

## Notes

- The host step (`steps/split_diff.py`) only parses stdout; the
  diff text itself never crosses the sandbox boundary.
