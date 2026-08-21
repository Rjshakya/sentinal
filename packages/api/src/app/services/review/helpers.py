"""Review pipeline helpers.

Pure functions used by the review workflow and its steps: no I/O,
no session, no clock. Every function here is testable with plain
``assert`` calls.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TypedDict

from app.models.code_comment import CodeComment
from app.models.enums import (
    CommentSeverity,
    CommentSide,
    CommentState,
)
from app.services.agent.models import CodeCommentDraft
from app.services.review.workflow_types import PRSizeStats
from app.utils.util import repo_path, uuidToStr


def get_repo_path(repo_name: str) -> str:
    """Return the in-sandbox path of the cloned ``repo_name``.

    Pure wrapper over :func:`app.utils.util.repo_path`. Lives in the
    pipeline so callers never have to know about the in-sandbox layout
    constants.
    """
    return repo_path(repo_name)


def get_review_diff_dir_path(pr_number: int, head_sha: str) -> str:
    """Return the in-sandbox directory holding the PR diff artefacts.

    Layout: ``/home/user/tmp/{pr_number}/{head_sha}/`` — ``file.diff``
    (the raw unified diff), ``overview.md``, and ``splitted_diffs/``
    (the per-file annotated chunks written by the split step).
    """
    return f"/home/user/tmp/{pr_number}/{head_sha}"


def map_drafts_to_comment_rows(
    *,
    pr_id: str,
    review_id: str | None,
    commit_id: str,
    comments: Sequence[CodeCommentDraft],
) -> list[CodeComment]:
    """Translate :class:`CodeCommentDraft` objects into ORM rows.

    Each draft becomes a :class:`CodeComment` keyed to ``(pr_id,
    commit_id)`` with ``state=ACTIVE`` and the run's ``review_id``
    when one exists. The agent's severity / side strings are coerced
    into the corresponding enums; a bad value raises ``ValueError``
    here (this is a programmer error, not a pipeline failure mode).
    """
    rows: list[CodeComment] = []
    for draft in comments:
        rows.append(
            CodeComment(
                id=uuidToStr(),
                pr_id=pr_id,
                review_id=review_id,
                commit_id=commit_id,
                file_name=draft.file_name,
                comment=draft.comment,
                severity=CommentSeverity(draft.severity),
                from_line=draft.from_line,
                to_line=draft.to_line,
                side=CommentSide(draft.side),
                node_type=draft.node_type,
                state=CommentState.ACTIVE,
            )
        )
    return rows


def create_review_workflow_id(*, repo_id: str, pr_number: int, head_sha: str) -> str:
    """Build the deterministic inner review workflow id.

    Mirrors the formula used by
    :func:`app.services.review.webhook.handle_pull_request_opened`
    so the inner workflow dedupes across triggers.
    """
    short_sha = head_sha[:7]
    return f"review:{repo_id}:{pr_number}:{short_sha}"


# Calibration for the per-run agent call limits. The cap is a ceiling,
# not a target: a PR with more files / lines gets more headroom so a
# large PR can complete without the middleware capping the agent
# mid-run, while small PRs keep a modest ceiling against runaway loops.
_REVIEW_LIMIT_BASE = 150
_REVIEW_LIMIT_PER_FILE = 40
_REVIEW_LIMIT_PER_LINE = 0.25
_REVIEW_LIMIT_MIN = 150
_REVIEW_LIMIT_MAX = 2000


@dataclass(frozen=True)
class ReviewLimits:
    """Per-run model/tool call limits for the review agents."""

    model_call_run_limit: int
    tool_call_run_limit: int


def compute_review_limits(pr_size: PRSizeStats) -> ReviewLimits:
    """Size the per-run agent call limits from the PR's size stats.

    Pure formula: the limit scales with the number of changed files and
    the total changed lines (``additions + deletions``). The same
    ceiling is applied to both the model-call and tool-call run limits,
    clamped to ``[_REVIEW_LIMIT_MIN, _REVIEW_LIMIT_MAX]`` so a huge PR
    cannot set an unbounded budget while a trivial PR still gets enough
    headroom to complete.
    """
    files = pr_size["changed_files"]
    lines = pr_size["additions"] + pr_size["deletions"]
    work = files * _REVIEW_LIMIT_PER_FILE + lines * _REVIEW_LIMIT_PER_LINE
    limit = int(_REVIEW_LIMIT_BASE + work)
    limit = max(_REVIEW_LIMIT_MIN, min(_REVIEW_LIMIT_MAX, limit))
    return ReviewLimits(
        model_call_run_limit=limit,
        tool_call_run_limit=limit,
    )


class SplitDiffResult(TypedDict):
    """The tiny summary JSON the in-sandbox split script prints on stdout.

    ``overview_written`` — whether ``overview.md`` was written.
    ``files_changed``  — number of per-file chunks created in ``splitted_diffs/``.
    ``skipped``        — paths that appeared in the diff but were not split
        (binary files, or rename-only sections with no hunks).

    Parsing lives here so ``scripts/split_diff.py``'s stdout is validated by
    exactly the same code in the host step (:mod:`...steps.split_diff`) and
    the dev harness (``test-data/test_split.py``).
    """

    overview_written: bool
    files_changed: int
    skipped: list[str]


def parse_split_summary(stdout: str) -> SplitDiffResult:
    """Parse and validate the script's single stdout JSON line.

    Raises:
        ValueError: the stdout is not a single JSON object with a boolean
            ``overview_written``, a non-negative ``files_changed``, and a
            string-list ``skipped``.
    """
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise ValueError(f"split summary is not valid JSON: {stdout[:200]!r}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"split summary is not a JSON object: {stdout[:200]!r}")

    overview_written = data.get("overview_written")
    if not isinstance(overview_written, bool):
        raise ValueError(
            f"split summary has no boolean overview_written: {stdout[:200]!r}"
        )
    files_changed = data.get("files_changed")
    if not isinstance(files_changed, int) or files_changed < 0:
        raise ValueError(
            f"split summary has no non-negative files_changed: {stdout[:200]!r}"
        )
    skipped = data.get("skipped")
    if not isinstance(skipped, list) or not all(isinstance(s, str) for s in skipped):
        raise ValueError(f"split summary has no string-list skipped: {stdout[:200]!r}")

    return SplitDiffResult(
        overview_written=overview_written,
        files_changed=files_changed,
        skipped=skipped,
    )


__all__ = [
    "ReviewLimits",
    "SplitDiffResult",
    "compute_review_limits",
    "create_review_workflow_id",
    "get_repo_path",
    "get_review_diff_dir_path",
    "map_drafts_to_comment_rows",
    "parse_split_summary",
]
