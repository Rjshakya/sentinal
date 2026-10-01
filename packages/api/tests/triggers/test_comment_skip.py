"""Unit tests for the comment-path same-head skip gate.

Covers :func:`app.workflows.triggers.comment_payload.isHeadAlreadyPosted`:
the pure decision behind the ``head_already_posted`` early return in
``reviewCommentHandler``. No DB, no GitHub, no durable runtime.
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.utils.branded import CommitId
from app.workflows.triggers.comment_payload import isHeadAlreadyPosted
from app.workflows.triggers.types import LastReviewSnapshot

_HEAD = "abc1234def5678901234567890abcdef12345678"


def _snapshot(commit_id: str, github_review_id: str | None) -> LastReviewSnapshot:
    return LastReviewSnapshot(
        commitId=CommitId(commit_id),
        baseSha="base-sha",
        createdAt=datetime.now(timezone.utc),
        githubReviewId=github_review_id,
    )


def test_no_last_review_never_skips() -> None:
    assert isHeadAlreadyPosted(apiHeadSha=_HEAD, lastReview=None) is False


def test_same_head_posted_skips() -> None:
    last = _snapshot(_HEAD, "123456")
    assert isHeadAlreadyPosted(apiHeadSha=_HEAD, lastReview=last) is True


def test_same_head_unposted_does_not_skip() -> None:
    """Success-but-never-posted keeps the manual retry lever (re-run)."""
    last = _snapshot(_HEAD, None)
    assert isHeadAlreadyPosted(apiHeadSha=_HEAD, lastReview=last) is False


def test_moved_head_does_not_skip() -> None:
    last = _snapshot("olderhead5678901234567890abcdef12345678", "123456")
    assert isHeadAlreadyPosted(apiHeadSha=_HEAD, lastReview=last) is False
