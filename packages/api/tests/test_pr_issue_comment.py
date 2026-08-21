"""Unit tests for the ``issue_comment`` trigger pipeline's pure helpers.

Covers the incremental-re-review decision
(:func:`app.services.pr_issue_comment.helpers.effective_diff_base`) and
the ``diff_base_sha`` propagation through
:func:`app.services.pr_issue_comment.helpers.build_review_workflow_input`,
so the whole comment-trigger data path is verified without DBOS /
sandbox / LLM I/O.
"""

from __future__ import annotations

from datetime import UTC, datetime

from app.core.llm import LLMConfig
from app.services.pr_issue_comment.helpers import (
    build_review_workflow_input,
    effective_diff_base,
)
from app.services.pr_issue_comment.types import (
    IssueCommentTriggerInput,
    LastReviewSnapshot,
)
from app.services.review.workflow_types import PRSizeStats, ReviewWorkflowInput


def _last_review(commit_id: str) -> LastReviewSnapshot:
    return LastReviewSnapshot(
        commit_id=commit_id,
        base_sha="base-original",
        created_at=datetime.now(UTC),
    )


def test_diff_base_none_without_prior_review() -> None:
    assert (
        effective_diff_base(
            api_base_sha="b",
            api_head_sha="h2",
            last_review=None,
        )
        is None
    )


def test_diff_base_none_when_head_unchanged() -> None:
    assert (
        effective_diff_base(
            api_base_sha="b",
            api_head_sha="h1",
            last_review=_last_review("h1"),
        )
        is None
    )


def test_diff_base_is_last_reviewed_head_when_head_moved() -> None:
    assert (
        effective_diff_base(
            api_base_sha="b",
            api_head_sha="h2",
            last_review=_last_review("h1"),
        )
        == "h1"
    )


def _trigger() -> IssueCommentTriggerInput:
    return IssueCommentTriggerInput(
        delivery="d",
        installation_id=1,
        repo_owner="owner",
        repo_name="repo",
        gh_repo_id=2,
        default_branch="main",
        pr_number=3,
        pr_author_login="alice",
        commenter_login="alice",
        author_association="OWNER",
        comment_id=4,
        comment_body="@ai-code-review review",
    )


def _size() -> PRSizeStats:
    return PRSizeStats(additions=10, deletions=0, changed_files=1)


def _build(
    *,
    trigger: IssueCommentTriggerInput,
    diff_base_sha: str | None,
) -> ReviewWorkflowInput:
    return build_review_workflow_input(
        trigger=trigger,
        gh_pr_id=99,
        base_sha="b",
        head_sha="h2",
        base_branch="main",
        head_branch="feat",
        title="t",
        body="body",
        author="alice",
        state="open",
        merged=False,
        pr_size=_size(),
        user_id="u",
        llm_config=LLMConfig(model="openai:gpt-5.5"),
        diff_base_sha=diff_base_sha,
    )


def test_build_review_workflow_input_propagates_diff_base_sha() -> None:
    review_input = _build(trigger=_trigger(), diff_base_sha="h1")
    assert review_input.diff_base_sha == "h1"
    assert review_input.base_sha == "b"
    assert review_input.head_sha == "h2"


def test_build_review_workflow_input_defaults_diff_base_sha_to_none() -> None:
    review_input = _build(trigger=_trigger(), diff_base_sha=None)
    assert review_input.diff_base_sha is None