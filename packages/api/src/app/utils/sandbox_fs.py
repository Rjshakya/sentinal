"""Single source of truth for the in-sandbox run layout.

The review pipeline runs pi inside an ephemeral sandbox rooted at
``~/.sentinel``::

    /home/user/.sentinel/
    ├── {repo_name}/                    <- PR-head checkout
    └── {head_sha}/                     <- one review run
        ├── plan.jsonl                 <- pi planner output
        ├── review.jsonl               <- pi file-review output
        ├── summary.jsonl              <- walkthrough + verdict
        └── diff/                      <- host-produced inputs (read-only for pi)
            ├── file.diff
            ├── overview.md
            └── splitted_diffs/

Pure string builders only: no I/O, no logging, no sandbox calls.
Callers resolve a path here and pass it to the sandbox (as a command
argument or prompt text). In-sandbox scripts never import this module
(they are uploaded as bytes and stay stdlib-only); the host passes
resolved paths as CLI argv instead.
"""

from __future__ import annotations

SANDBOX_HOME: str = "/home/user"
SENTINEL_DIR_NAME: str = ".sentinel"
DIFF_DIR_NAME: str = "diff"
SPLIT_DIR_NAME: str = "splitted_diffs"
DIFF_FILE_NAME: str = "file.diff"
OVERVIEW_FILE_NAME: str = "overview.md"
PLAN_FILE_NAME: str = "plan.jsonl"
REVIEW_FILE_NAME: str = "review.jsonl"
SUMMARY_FILE_NAME: str = "summary.jsonl"


def _checkSegment(value: str, *, field: str) -> str:
    """Validate a single path segment (no traversal, no nesting)."""
    if not value:
        raise ValueError(f"{field} must be non-empty")
    if "/" in value or value in (".", ".."):
        raise ValueError(f"{field} must be a single path segment: {value!r}")
    return value


def sentinelRoot() -> str:
    """Return the in-sandbox sentinel root (``~/.sentinel``)."""
    return f"{SANDBOX_HOME}/{SENTINEL_DIR_NAME}"


def getRepoDir(repoName: str) -> str:
    """Return the in-sandbox directory of the cloned ``repoName``."""
    return f"{sentinelRoot()}/{_checkSegment(repoName, field='repoName')}"


def getReviewDir(headSha: str) -> str:
    """Return the in-sandbox review-run directory for ``headSha``."""
    return f"{sentinelRoot()}/{_checkSegment(headSha, field='headSha')}"


def getDiffDir(headSha: str) -> str:
    """Return the host-produced diff-input directory for ``headSha``."""
    return f"{getReviewDir(headSha)}/{DIFF_DIR_NAME}"


def getDiffFile(headSha: str) -> str:
    """Return the raw unified diff path for ``headSha``."""
    return f"{getDiffDir(headSha)}/{DIFF_FILE_NAME}"


def getOverviewFile(headSha: str) -> str:
    """Return the what-changed overview path for ``headSha``."""
    return f"{getDiffDir(headSha)}/{OVERVIEW_FILE_NAME}"


def getSplittedDir(headSha: str) -> str:
    """Return the per-file chunk directory for ``headSha``."""
    return f"{getDiffDir(headSha)}/{SPLIT_DIR_NAME}"


def getPlanFile(headSha: str) -> str:
    """Return the pi planner-output path for ``headSha``."""
    return f"{getReviewDir(headSha)}/{PLAN_FILE_NAME}"


def getReviewFile(headSha: str) -> str:
    """Return the pi file-review-output path for ``headSha``."""
    return f"{getReviewDir(headSha)}/{REVIEW_FILE_NAME}"


def getSummaryFile(headSha: str) -> str:
    """Return the walkthrough + verdict path for ``headSha``."""
    return f"{getReviewDir(headSha)}/{SUMMARY_FILE_NAME}"


__all__ = [
    "DIFF_DIR_NAME",
    "DIFF_FILE_NAME",
    "OVERVIEW_FILE_NAME",
    "PLAN_FILE_NAME",
    "REVIEW_FILE_NAME",
    "SANDBOX_HOME",
    "SENTINEL_DIR_NAME",
    "SPLIT_DIR_NAME",
    "SUMMARY_FILE_NAME",
    "getDiffDir",
    "getDiffFile",
    "getOverviewFile",
    "getPlanFile",
    "getRepoDir",
    "getReviewDir",
    "getReviewFile",
    "getSplittedDir",
    "getSummaryFile",
    "sentinelRoot",
]
