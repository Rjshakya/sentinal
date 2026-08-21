"""Unit tests for the per-run review agent call limits.

Covers the pure size-to-limits helper
(:func:`app.services.review.helpers.compute_review_limits`) and the two
trigger-side ``pr_size`` projections (the ``pull_request`` webhook
:func:`app.services.review.webhook.extract_payload` and the comment
path's :func:`app.services.pr_issue_comment.steps.fetch_pr_state._pr_state_from_response`),
so the whole data path is verified without DBOS / sandbox / LLM I/O.
"""

from __future__ import annotations

import types

import pytest

from app.services.pr_issue_comment.steps.fetch_pr_state import _pr_state_from_response
from app.services.review.helpers import (
    ReviewLimits,
    _REVIEW_LIMIT_MAX,
    _REVIEW_LIMIT_MIN,
    compute_review_limits,
)
from app.services.review.webhook import extract_payload
from app.services.review.workflow_types import PRSizeStats, ReviewWorkflowInput


def _size(
    *, additions: int = 0, deletions: int = 0, changed_files: int = 0
) -> PRSizeStats:
    return PRSizeStats(
        additions=additions,
        deletions=deletions,
        changed_files=changed_files,
    )


def test_zero_size_pr_gets_min_limits() -> None:
    limits = compute_review_limits(_size())
    assert limits == ReviewLimits(
        model_call_run_limit=_REVIEW_LIMIT_MIN,
        tool_call_run_limit=_REVIEW_LIMIT_MIN,
    )


def test_limits_scale_with_files_and_lines() -> None:
    small = compute_review_limits(
        _size(additions=10, deletions=5, changed_files=2)
    )
    large = compute_review_limits(
        _size(additions=500, deletions=200, changed_files=20)
    )
    assert large.model_call_run_limit > small.model_call_run_limit
    assert large.tool_call_run_limit > small.tool_call_run_limit


def test_limits_are_equal_for_model_and_tool() -> None:
    limits = compute_review_limits(
        _size(additions=100, deletions=40, changed_files=8)
    )
    assert limits.model_call_run_limit == limits.tool_call_run_limit


def test_limits_are_clamped_at_max() -> None:
    huge = compute_review_limits(
        _size(additions=100_000, deletions=100_000, changed_files=10_000)
    )
    assert huge.model_call_run_limit == _REVIEW_LIMIT_MAX
    assert huge.tool_call_run_limit == _REVIEW_LIMIT_MAX


def test_workflow_input_defaults_pr_size_to_zero() -> None:
    from app.core.llm import LLMConfig
    from app.models.enums import PRStatus

    input = ReviewWorkflowInput(
        user_id="u",
        gh_repo_id=1,
        pr_id=2,
        pr_number=3,
        branch="main",
        base_sha="b",
        head_sha="h",
        head_branch="feat",
        author="alice",
        body="",
        title="t",
        status=PRStatus.OPEN,
        llm_config=LLMConfig(model="openai:gpt-5.5"),
        post_to_github=False,
    )
    assert input.pr_size == {
        "additions": 0,
        "deletions": 0,
        "changed_files": 0,
    }


def _pr_payload(**overrides: object) -> dict:
    base: dict = {
        "id": 2,
        "number": 3,
        "base": {"ref": "main", "sha": "b"},
        "head": {"ref": "feat", "sha": "h"},
        "user": {"login": "alice"},
        "title": "t",
        "body": "b",
        "state": "open",
    }
    base.update(overrides)
    return {
        "repository": {"id": 1, "default_branch": "main"},
        "pull_request": base,
    }


def test_extract_payload_populates_pr_size() -> None:
    parsed = extract_payload(
        _pr_payload(additions=12, deletions=3, changed_files=4)
    )
    assert parsed is not None
    assert parsed.pr_size == {
        "additions": 12,
        "deletions": 3,
        "changed_files": 4,
    }


def test_extract_payload_coerces_missing_pr_size_to_zero() -> None:
    parsed = extract_payload(_pr_payload())
    assert parsed is not None
    assert parsed.pr_size == {
        "additions": 0,
        "deletions": 0,
        "changed_files": 0,
    }


class _FakePR:
    """Minimal githubkit-like PR object with just the projected fields."""

    head = types.SimpleNamespace(sha="h", ref="feat")
    base = types.SimpleNamespace(sha="b", ref="main")
    user = types.SimpleNamespace(login="alice")

    def __init__(
        self,
        *,
        additions: int = 0,
        deletions: int = 0,
        changed_files: int = 0,
    ) -> None:
        self.id = 7
        self.title = "t"
        self.body = "b"
        self.state = "open"
        self.merged = False
        self.additions = additions
        self.deletions = deletions
        self.changed_files = changed_files


def test_pr_state_from_response_populates_pr_size() -> None:
    snapshot = _pr_state_from_response(
        _FakePR(additions=50, deletions=10, changed_files=6)
    )
    assert snapshot.pr_size == {
        "additions": 50,
        "deletions": 10,
        "changed_files": 6,
    }


def test_pr_state_from_response_defaults_missing_pr_size_to_zero() -> None:
    snapshot = _pr_state_from_response(_FakePR())
    assert snapshot.pr_size == {
        "additions": 0,
        "deletions": 0,
        "changed_files": 0,
    }


@pytest.mark.parametrize(
    ("stats", "expected"),
    [
        (_size(), _REVIEW_LIMIT_MIN),
        (_size(additions=10, deletions=5, changed_files=2), 233),
        (_size(additions=500, deletions=200, changed_files=20), 1125),
    ],
)
def test_limits_formula_spot_checks(stats: PRSizeStats, expected: int) -> None:
    limits = compute_review_limits(stats)
    assert limits.model_call_run_limit == expected
    assert limits.tool_call_run_limit == expected