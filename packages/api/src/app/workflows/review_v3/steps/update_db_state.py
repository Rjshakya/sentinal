"""Single-transaction db state: upsert PR + mark review running.

One session, one commit: the ``pull_requests`` row (keyed on
``(repo_id, number)``) and the ``review`` lifecycle row (keyed on the
deterministic ``workflow_id``) are written atomically, so a retry can
never leave a PR row without its review row. The caller owns the
session; this step never commits on its own — it commits once.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.enums import PRStatus
from app.models.pull_request import PullRequest
from app.models.review import Review, ReviewState
from app.repositories.pull_request import PullRequestRepository
from app.repositories.review import ReviewRepository
from app.utils.branded import (
    CommitId,
    PRNumber,
    PrRowId,
    RepoId,
    ReviewRowId,
    UserId,
)
from app.utils.util import uuidToStr
from app.workflows.review_v3.errors import DbStateError
from app.workflows.review_v3.types import UpdateDbStateResult


async def updateDbState(
    session: AsyncSession,
    *,
    userId: UserId,
    repoId: RepoId,
    ghRepoId: int,
    prNumber: PRNumber,
    author: str,
    title: str,
    body: str | None,
    status: PRStatus,
    baseBranch: str,
    baseSha: str,
    headBranch: str,
    headSha: CommitId,
    sandboxId: str,
    workflowId: str,
    trigger: str,
    llmProvider: str | None,
    llmClient: str | None,
    llmModel: str | None,
    llmBaseUrl: str | None,
) -> UpdateDbStateResult | DbStateError:
    """Upsert the PR row and flip the review row to RUNNING, atomically."""
    if not workflowId:
        raise ValueError("workflowId must be non-empty")
    if not sandboxId:
        raise ValueError("sandboxId must be non-empty")
    try:
        prs = PullRequestRepository(session=session)
        existingPr = await prs.find_by_repo_and_number(str(repoId), int(prNumber))
        if existingPr is not None:
            existingPr.base_branch = baseBranch
            existingPr.base_sha = baseSha
            existingPr.head_branch = headBranch
            existingPr.head_sha = str(headSha)
            existingPr.title = title
            existingPr.body = body
            existingPr.author = author
            existingPr.status = status
            existingPr.updated_at = datetime.now(UTC)
            await prs.add(existingPr)
            prId = str(existingPr.id)
        else:
            pr = PullRequest(
                id=uuidToStr(),
                repo_id=str(repoId),
                number=int(prNumber),
                author=author,
                title=title,
                body=body,
                status=status,
                base_branch=baseBranch,
                base_sha=baseSha,
                head_branch=headBranch,
                head_sha=str(headSha),
            )
            await prs.add(pr)
            prId = str(pr.id)

        reviews = ReviewRepository(session=session)
        existingReview = await reviews.find_by_workflow_id(workflowId)
        if existingReview is not None:
            existingReview.state = ReviewState.RUNNING
            existingReview.pr_id = prId
            existingReview.sandbox_id = sandboxId
            existingReview.llm_provider = llmProvider
            existingReview.llm_client = llmClient
            existingReview.llm_model = llmModel
            existingReview.llm_base_url = llmBaseUrl
            existingReview.error_name = None
            existingReview.error_message = None
            existingReview.error_context = None
            if existingReview.started_at is None:
                existingReview.started_at = datetime.now(UTC)
            existingReview.updated_at = datetime.now(UTC)
            await reviews.add(existingReview)
            reviewId = str(existingReview.id)
        else:
            review = Review(
                user_id=str(userId),
                repo_id=str(repoId),
                gh_repo_id=ghRepoId,
                pr_id=prId,
                pr_number=int(prNumber),
                commit_id=str(headSha),
                base_sha=baseSha,
                workflow_id=workflowId,
                trigger=trigger,
                state=ReviewState.RUNNING,
                sandbox_id=sandboxId,
                llm_provider=llmProvider,
                llm_client=llmClient,
                llm_model=llmModel,
                llm_base_url=llmBaseUrl,
                started_at=datetime.now(UTC),
            )
            await reviews.add(review)
            reviewId = str(review.id)

        await session.commit()
    except Exception as exc:
        return DbStateError(
            message=f"db state update failed: {type(exc).__name__}: {exc}"
        )
    return UpdateDbStateResult(
        prRowId=PrRowId(prId), reviewRowId=ReviewRowId(reviewId)
    )


__all__ = ["updateDbState"]
