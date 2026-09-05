"""End-to-end test for the review workflow.

Runs the full durable review pipeline
(:func:`app.workflows.review.workflow.reviewWorkflow`) against a real
PR on a public repo — real Postgres + DBOS, real E2B sandbox, real
LLM — and drives the assertions from the workflow's returned
:class:`ReviewRunResult` plus every DB row it wrote (``pull_requests``
/ ``review`` / ``review_summaries`` / ``code_comments`` /
``review_usages``).

Inputs (env; defaults pin ``Rjshakya/code-review-test`` PR #2 "Add
endpoints"): REVIEW_E2E_REPO_OWNER, REVIEW_E2E_REPO_NAME,
REVIEW_E2E_GH_REPO_ID, REVIEW_E2E_GH_PR_ID, REVIEW_E2E_PR_NUMBER,
REVIEW_E2E_BASE_BRANCH, REVIEW_E2E_HEAD_BRANCH, REVIEW_E2E_BASE_SHA,
REVIEW_E2E_HEAD_SHA, REVIEW_E2E_AUTHOR, REVIEW_E2E_TITLE,
REVIEW_E2E_ADDITIONS, REVIEW_E2E_DELETIONS, REVIEW_E2E_CHANGED_FILES,
REVIEW_E2E_USER_ID, REVIEW_E2E_REPO_LOCAL_ID,
REVIEW_E2E_INSTALLATION_ID (required), REVIEW_E2E_POST_TO_GITHUB
(default off), REVIEW_E2E_TIMEOUT_S.

Run: cd packages/api && uv run pytest tests/test_review_e2e.py -v
"""

from __future__ import annotations

import os
from collections.abc import AsyncGenerator
from typing import cast

import pytest
from conftest import run_review_workflow
from dbos import WorkflowStatusString
from sqlalchemy import ColumnElement, delete
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.core.db import async_session_maker
from app.models.code_comment import CodeComment
from app.models.enums import CommentState, PRStatus, ReviewRunStatus, ReviewVerdict
from app.models.pull_request import PullRequest
from app.models.repo import Repo
from app.models.review import Review, ReviewState
from app.models.review_summary import ReviewSummary
from app.models.review_usage import ReviewUsage
from app.services.llm import createDefaultLLMContext
from app.services.sandbox.service import (
    DEFAULT_ROOT_PATH,
    createSandboxCtx,
    getDefaulSandboxName,
)
from app.services.sandbox.types import ProviderId, SanboxProviderApiKey
from app.utils.branded import (
    CommitId,
    InstallationId,
    PRNumber,
    RepoId,
    RepoName,
    RepoOwner,
    UserId,
)
from app.utils.schema import CodeCommentDraft
from app.workflows.review.types import ReviewRunResult, ReviewWorkflowCtx
from app.workflows.review.workflow import (
    buildReviewWorkflowInput,
    createReviewWorkflowId,
)

REVIEW_E2E_REPO_OWNER = os.environ.get("REVIEW_E2E_REPO_OWNER", "Rjshakya")
REVIEW_E2E_REPO_NAME = os.environ.get("REVIEW_E2E_REPO_NAME", "code-review-test")
REVIEW_E2E_GH_REPO_ID = int(os.environ.get("REVIEW_E2E_GH_REPO_ID", "1298419702"))
REVIEW_E2E_GH_PR_ID = int(os.environ.get("REVIEW_E2E_GH_PR_ID", "4395127676"))
REVIEW_E2E_PR_NUMBER = int(os.environ.get("REVIEW_E2E_PR_NUMBER", "2"))
REVIEW_E2E_BASE_BRANCH = os.environ.get("REVIEW_E2E_BASE_BRANCH", "main")
REVIEW_E2E_HEAD_BRANCH = os.environ.get("REVIEW_E2E_HEAD_BRANCH", "add-endpoints")
REVIEW_E2E_BASE_SHA = os.environ.get(
    "REVIEW_E2E_BASE_SHA", "c9488afc7738734ddd93dc927470700e4434a9db"
)
REVIEW_E2E_HEAD_SHA = os.environ.get(
    "REVIEW_E2E_HEAD_SHA", "6c759629989ab83133f2b04217ff4e4db1a88594"
)
REVIEW_E2E_AUTHOR = os.environ.get("REVIEW_E2E_AUTHOR", "Rjshakya")
REVIEW_E2E_TITLE = os.environ.get("REVIEW_E2E_TITLE", "Add endpoints")
REVIEW_E2E_ADDITIONS = int(os.environ.get("REVIEW_E2E_ADDITIONS", "94"))
REVIEW_E2E_DELETIONS = int(os.environ.get("REVIEW_E2E_DELETIONS", "6"))
REVIEW_E2E_CHANGED_FILES = int(os.environ.get("REVIEW_E2E_CHANGED_FILES", "1"))
REVIEW_E2E_USER_ID = os.environ.get("REVIEW_E2E_USER_ID", "e2e-review-user")
REVIEW_E2E_REPO_LOCAL_ID = os.environ.get(
    "REVIEW_E2E_REPO_LOCAL_ID",
    "e2e-review-repo-00000000-0000-0000-0000-000000000000",
)
REVIEW_E2E_POST_TO_GITHUB = True
REVIEW_TIMEOUT_S: float = float(os.environ.get("REVIEW_E2E_TIMEOUT_S", "1200"))


def _expected_verdict(comments: list[CodeCommentDraft]) -> str:
    """Recompute the deterministic verdict rule the pipeline uses."""
    if any(c.severity == "P1_CRITICAL" for c in comments):
        return "REQUEST_CHANGES"
    if comments:
        return "COMMENT"
    return "APPROVE"


async def _seed_repo(session: AsyncSession) -> Repo:
    """Upsert the local ``repos`` row the workflow's ``getRepoTx`` step reads."""
    repo = (
        await session.exec(
            select(Repo).where(Repo.github_repo_id == REVIEW_E2E_GH_REPO_ID)
        )
    ).first()
    if repo is not None:
        return repo

    repo = Repo(
        id=REVIEW_E2E_REPO_LOCAL_ID,
        user_id=REVIEW_E2E_USER_ID,
        github_repo_id=REVIEW_E2E_GH_REPO_ID,
        repo_name=REVIEW_E2E_REPO_NAME,
        repo_owner=REVIEW_E2E_REPO_OWNER,
        clone_url=f"https://github.com/{REVIEW_E2E_REPO_OWNER}/{REVIEW_E2E_REPO_NAME}.git",
        private=False,
        default_branch=REVIEW_E2E_BASE_BRANCH,
    )
    session.add(repo)
    await session.commit()
    await session.refresh(repo)
    return repo


@pytest.fixture
async def cleanup_review_e2e_rows() -> AsyncGenerator[None, None]:
    """Teardown: remove every row the review run wrote so re-runs start clean.

    Deleting the ``pull_requests`` row cascades at the DB layer to the
    ``review`` / ``review_summaries`` / ``code_comments`` /
    ``review_usages`` rows (all keyed on ``pr_id`` / ``review_id`` with
    CASCADE). The seeded ``repos`` row is removed too, so
    :func:`_seed_repo` recreates it on the next run. Runs even when the
    test fails, so a mid-pipeline crash leaves no partial rows behind.
    """
    yield
    async with async_session_maker() as session:
        repo = (
            await session.exec(
                select(Repo).where(Repo.github_repo_id == REVIEW_E2E_GH_REPO_ID)
            )
        ).first()
        if repo is None:
            return
        await session.exec(
            delete(PullRequest).where(
                cast(ColumnElement[bool], PullRequest.repo_id == repo.id)
            )
        )
        await session.exec(
            delete(Repo).where(cast(ColumnElement[bool], Repo.id == repo.id))
        )
        await session.commit()


def _build_workflow_ctx(*, repo: Repo) -> ReviewWorkflowCtx:
    """Assemble the run env exactly like the trigger adapters (settings-driven)."""
    provider = cast(ProviderId, settings.sandbox_provider)
    api_key = settings.e2b_api_key
    sandbox_ctx = createSandboxCtx(
        userId=UserId(REVIEW_E2E_USER_ID),
        repoId=RepoId(repo.id),
        repoName=repo.repo_name,
        providerId=provider,
        apiKey=SanboxProviderApiKey(api_key),
        sandboxName=getDefaulSandboxName(repo.repo_name),
        rootPath=DEFAULT_ROOT_PATH[provider],
    )
    return ReviewWorkflowCtx(
        llmCtx=createDefaultLLMContext(),
        sandboxCtx=sandbox_ctx,
    )


async def test_review_workflow_end_to_end(
    workflow_salt: str,
    requires_review_env: None,
    cleanup_review_e2e_rows: None,
) -> None:
    """Full pipeline: sandbox -> clone -> diff -> agents -> extract -> persist."""
    installation_id = InstallationId(int(settings.review_e2e_installation_id))

    async with async_session_maker() as session:
        repo = await _seed_repo(session)

    workflow_ctx = _build_workflow_ctx(repo=repo)
    workflow_input = buildReviewWorkflowInput(
        userId=UserId(REVIEW_E2E_USER_ID),
        ghRepoId=REVIEW_E2E_GH_REPO_ID,
        ghPrId=REVIEW_E2E_GH_PR_ID,
        prNumber=PRNumber(REVIEW_E2E_PR_NUMBER),
        baseBranch=REVIEW_E2E_BASE_BRANCH,
        defaultBranch=REVIEW_E2E_BASE_BRANCH,
        baseSha=REVIEW_E2E_BASE_SHA,
        headBranch=REVIEW_E2E_HEAD_BRANCH,
        headSha=CommitId(REVIEW_E2E_HEAD_SHA),
        author=REVIEW_E2E_AUTHOR,
        title=REVIEW_E2E_TITLE,
        body="",
        status=PRStatus.OPEN,
        prSize={
            "additions": REVIEW_E2E_ADDITIONS,
            "deletions": REVIEW_E2E_DELETIONS,
            "changedFiles": REVIEW_E2E_CHANGED_FILES,
        },
        githubInstallationId=installation_id,
        postToGithub=REVIEW_E2E_POST_TO_GITHUB,
        trigger="opened",
    )

    workflow_id = (
        createReviewWorkflowId(
            repoId=RepoId(repo.id),
            prNumber=PRNumber(REVIEW_E2E_PR_NUMBER),
            headSha=REVIEW_E2E_HEAD_SHA,
        )
        + ":"
        + workflow_salt
    )

    actual_id, output, status = await run_review_workflow(
        workflow_ctx,
        workflow_input,
        workflow_id=workflow_id,
        timeout_s=REVIEW_TIMEOUT_S,
    )
    assert actual_id == workflow_id
    assert workflow_id.startswith(f"review:{repo.id}:{REVIEW_E2E_PR_NUMBER}:")

    assert output is not None, "reviewWorkflow returned no output on SUCCESS"
    result = ReviewRunResult.model_validate(output)

    assert result.commitId == REVIEW_E2E_HEAD_SHA
    assert result.review.summary.strip(), "expected a non-empty review summary"
    assert result.review.verdict in ("APPROVE", "COMMENT", "REQUEST_CHANGES")
    assert result.review.verdict == _expected_verdict(result.review.comments)
    for draft in result.review.comments:
        assert draft.file_name, "every comment must name a file"
        assert draft.comment.strip(), "every comment must carry a body"
        assert draft.from_line >= 0 and draft.to_line >= 0

    assert result.usages["pr_number"] == REVIEW_E2E_PR_NUMBER
    assert result.usages["repo_id"] == repo.id
    assert result.usages["user_id"] == REVIEW_E2E_USER_ID
    assert result.usages["head_sha"] == REVIEW_E2E_HEAD_SHA
    assert result.usages["usages"], "expected per-model token usage"
    assert all(usage["total_tokens"] > 0 for usage in result.usages["usages"].values())

    async with async_session_maker() as session:
        pr_row = (
            await session.exec(
                select(PullRequest).where(
                    PullRequest.repo_id == repo.id,
                    PullRequest.number == REVIEW_E2E_PR_NUMBER,
                )
            )
        ).first()
        assert pr_row is not None
        assert pr_row.id == result.prRowId
        assert pr_row.head_sha == REVIEW_E2E_HEAD_SHA
        assert pr_row.base_sha == REVIEW_E2E_BASE_SHA
        assert pr_row.status == PRStatus.OPEN

        review_row = (
            await session.exec(select(Review).where(Review.workflow_id == workflow_id))
        ).first()
        assert review_row is not None
        assert review_row.state == ReviewState.SUCCESS
        assert review_row.repo_id == repo.id
        assert review_row.pr_id == result.prRowId
        assert review_row.pr_number == REVIEW_E2E_PR_NUMBER
        assert review_row.commit_id == REVIEW_E2E_HEAD_SHA
        assert review_row.base_sha == REVIEW_E2E_BASE_SHA
        assert review_row.trigger == "opened"
        assert review_row.comment_count == len(result.review.comments)
        assert review_row.sandbox_id is not None
        assert review_row.started_at is not None
        assert review_row.completed_at is not None
        assert review_row.llm_provider == "system"
        assert review_row.llm_client is not None
        assert review_row.llm_model is not None

        summary_row = (
            await session.exec(
                select(ReviewSummary).where(ReviewSummary.review_id == review_row.id)
            )
        ).first()
        assert summary_row is not None
        assert summary_row.pr_id == result.prRowId
        assert summary_row.commit_id == REVIEW_E2E_HEAD_SHA
        assert summary_row.summary == result.review.summary
        assert summary_row.verdict == ReviewVerdict(result.review.verdict)

        comment_rows = (
            await session.exec(
                select(CodeComment).where(CodeComment.review_id == review_row.id)
            )
        ).all()
        assert len(comment_rows) == len(result.review.comments)
        assert {
            (c.file_name, c.comment, c.severity, c.from_line, c.to_line)
            for c in result.review.comments
        } == {
            (r.file_name, r.comment, r.severity.value, r.from_line, r.to_line)
            for r in comment_rows
        }
        for row in comment_rows:
            assert row.pr_id == result.prRowId
            assert row.commit_id == REVIEW_E2E_HEAD_SHA
            assert row.state == CommentState.ACTIVE

        usage_rows = (
            await session.exec(
                select(ReviewUsage).where(ReviewUsage.review_id == review_row.id)
            )
        ).all()
        assert len(usage_rows) == 1
        usage = usage_rows[0]
        assert usage.review_status == ReviewRunStatus.SUCCESS
        assert usage.total_tokens > 0
        assert usage.pr_id == result.prRowId
        assert usage.repo_id == repo.id
        assert usage.llm_model_id is not None
        assert usage.llm_provider is not None

        if REVIEW_E2E_POST_TO_GITHUB:
            assert review_row.github_review_id is not None
            # assert all(row.github_comment_id is not None for row in comment_rows)
