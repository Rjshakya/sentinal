"""Lifecycle steps: record the review run's state onto the ``review`` table.

- :func:`markReviewRunningStep` — find-or-create the ``review`` row for
  the current workflow and flip it to ``RUNNING`` (records the pr link,
  sandbox, and the LLM snapshot); returns the row id. Find-or-create
  keeps retries idempotent via the unique ``workflow_id``.
- :func:`markReviewStoppedStep` — flip to ``SUCCESS`` with the surviving
  comment count and the GitHub review id (when the post step returned
  one).
- :func:`markReviewErroredStep` — flip to ``FAILED`` with the error
  name / message; no-ops when no row id exists yet.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from app.core.db import async_session_maker
from app.models.review import Review, ReviewState
from app.repositories.review import ReviewRepository
from app.utils.branded import PrRowId, RepoId, ReviewRowId, UserId
from app.workflows.review_v2.errors import (
    LifecycleUpdateError,
    TransientReviewStepFailure,
)
from app.workflows.review_v2.types import RepoSnapshot, ReviewWorkflowInput

log = logging.getLogger(__name__)


def utcnow() -> datetime:
    return datetime.now(UTC)


def lifecycleError(
    message: str, *, userId: UserId, repoId: RepoId
) -> TransientReviewStepFailure:
    return TransientReviewStepFailure(
        LifecycleUpdateError(message=message, userId=userId, repoId=repoId)
    )


async def markReviewRunningStep(
    *,
    userId: UserId,
    repo: RepoSnapshot,
    input: ReviewWorkflowInput,
    prRowId: PrRowId,
    sandboxId: str,
    workflowId: str,
    llmProvider: str,
    llmClient: str | None,
    llmModel: str,
    llmBaseUrl: str | None,
) -> ReviewRowId:
    """Find-or-create the ``RUNNING`` row for this run; returns its id.

    ``llmProvider`` is the config source (``"system"`` / ``"user"``);
    ``llmClient`` the actual provider from the ``"provider:model"``
    string.

    Raises:
        TransientReviewStepFailure: the row could not be written.
    """
    try:
        async with async_session_maker() as session:
            reviews = ReviewRepository(session=session)
            existing = await reviews.find_by_workflow_id(workflowId)
            if existing is not None:
                existing.state = ReviewState.RUNNING
                existing.pr_id = prRowId
                existing.sandbox_id = sandboxId
                existing.llm_provider = llmProvider
                existing.llm_client = llmClient
                existing.llm_model = llmModel
                existing.llm_base_url = llmBaseUrl
                existing.error_name = None
                existing.error_message = None
                existing.error_context = None
                if existing.started_at is None:
                    existing.started_at = utcnow()
                existing.updated_at = utcnow()
                await session.commit()
                result = ReviewRowId(existing.id)
            else:
                review = Review(
                    user_id=userId,
                    repo_id=repo.id,
                    gh_repo_id=input.ghRepoId,
                    pr_id=prRowId,
                    pr_number=input.prNumber,
                    commit_id=input.headSha,
                    base_sha=input.baseSha,
                    workflow_id=workflowId,
                    trigger=input.trigger,
                    state=ReviewState.RUNNING,
                    sandbox_id=sandboxId,
                    llm_provider=llmProvider,
                    llm_client=llmClient,
                    llm_model=llmModel,
                    llm_base_url=llmBaseUrl,
                    started_at=utcnow(),
                )
                await reviews.add(review)
                await session.commit()
                await session.refresh(review)
                result = ReviewRowId(review.id)
    except Exception as exc:
        raise lifecycleError(
            f"mark running failed for workflow_id={workflowId} "
            f"repo_id={repo.id} pr_number={input.prNumber}: "
            f"{type(exc).__name__}: {exc}",
            userId=userId,
            repoId=repo.id,
        ) from exc
    log.info(
        "mark_review_running_step: ok review_id=%s workflow_id=%s "
        "repo_id=%s pr_number=%s",
        result,
        workflowId,
        repo.id,
        input.prNumber,
    )
    return result


async def markReviewStoppedStep(
    *,
    reviewRowId: ReviewRowId,
    commentCount: int,
    githubReviewId: str | None,
    userId: UserId,
    repoId: RepoId,
) -> None:
    """Flip the row to ``SUCCESS``.

    Raises:
        TransientReviewStepFailure: the row could not be updated.
    """
    try:
        async with async_session_maker() as session:
            reviews = ReviewRepository(session=session)
            review = await reviews.get(reviewRowId)
            if review is None:
                raise RuntimeError(f"review {reviewRowId!r} not found")
            review.state = ReviewState.SUCCESS
            review.comment_count = commentCount
            review.github_review_id = githubReviewId
            review.completed_at = utcnow()
            review.updated_at = utcnow()
            await session.commit()
    except Exception as exc:
        raise lifecycleError(
            f"mark stopped failed for review_id={reviewRowId}: "
            f"{type(exc).__name__}: {exc}",
            userId=userId,
            repoId=repoId,
        ) from exc
    log.info(
        "mark_review_stopped_step: ok review_id=%s comments=%d "
        "github_review_id=%s",
        reviewRowId,
        commentCount,
        githubReviewId,
    )


async def markReviewErroredStep(
    *,
    reviewRowId: ReviewRowId | None,
    errorName: str,
    errorMessage: str,
    errorContext: dict | None,
    userId: UserId,
    repoId: RepoId,
) -> None:
    """Flip the row to ``FAILED`` and persist the error.

    No-ops when ``reviewRowId`` is ``None``.

    Raises:
        TransientReviewStepFailure: the row could not be updated.
    """
    if reviewRowId is None:
        return
    try:
        async with async_session_maker() as session:
            reviews = ReviewRepository(session=session)
            review = await reviews.get(reviewRowId)
            if review is None:
                raise RuntimeError(f"review {reviewRowId!r} not found")
            review.state = ReviewState.FAILED
            review.error_name = errorName
            review.error_message = errorMessage
            review.error_context = errorContext
            review.completed_at = utcnow()
            review.updated_at = utcnow()
            await session.commit()
    except Exception as exc:
        raise lifecycleError(
            f"mark errored failed for review_id={reviewRowId}: "
            f"{type(exc).__name__}: {exc}",
            userId=userId,
            repoId=repoId,
        ) from exc
    log.info(
        "mark_review_errored_step: ok review_id=%s error=%s",
        reviewRowId,
        errorName,
    )


__all__ = [
    "markReviewErroredStep",
    "markReviewRunningStep",
    "markReviewStoppedStep",
    "utcnow",
]
