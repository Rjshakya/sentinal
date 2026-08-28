"""DBOS steps that record the review workflow's lifecycle onto the
``review`` table.

Three value-returning helpers (one per state transition) plus the pure
error-context projection:

- :func:`markReviewRunning` — find-or-create the ``review`` row for the
  current workflow and flip it to ``RUNNING`` (records the pr link,
  sandbox, and the LLM snapshot); returns the row id.
- :func:`markReviewStopped` — flip to ``SUCCESS`` with the surviving
  comment count and the GitHub review id (when the post step returned
  one).
- :func:`markReviewErrored` — flip to ``FAILED`` with the typed error
  name / message / context; no-ops when no row id exists yet.
- :func:`buildErrorContext` — pure; projects an exception onto the
  ``error_context`` JSONB shape.

Each edge step is durable (``retries_allowed=True``,
``should_retry=shouldRetry``): a DB blip is retried, and a persistent
failure surfaces as a workflow ERROR instead of leaving the row stuck
in ``RUNNING``. The running step's find-or-create semantics make
retries idempotent via the unique ``workflow_id``.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from dbos import DBOS
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.core.db import async_session_maker
from app.models.review import Review, ReviewState
from app.utils.branded import PrRowId, RepoId, ReviewRowId, UserId
from app.workflows.review.errors import (
    LifecycleUpdateError,
    ReviewAgentsError,
    TransientReviewStepFailure,
    shouldRetry,
)
from app.workflows.review.types import RepoSnapshot, ReviewWorkflowInput

log = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(UTC)


async def markReviewRunning(
    session: AsyncSession,
    *,
    userId: UserId,
    repo: RepoSnapshot,
    input: ReviewWorkflowInput,
    prRowId: PrRowId,
    sandboxId: str,
    workflowId: str,
    llmProvider: str,
    llmModel: str,
    llmBaseUrl: str | None,
) -> ReviewRowId | LifecycleUpdateError:
    """Find-or-create the ``RUNNING`` row for the current workflow.

    Uses ``workflowId`` as the deterministic DBOS id so the row is
    unique per run and duplicate dispatches / workflow restarts reuse
    it. On restart the existing row is reset to ``RUNNING`` and its
    error fields cleared (``started_at`` is kept from the original
    attempt).
    """
    try:
        existing = (
            (
                await session.execute(
                    select(Review).where(Review.workflow_id == workflowId)
                )
            )
            .scalars()
            .first()
        )

        if existing is not None:
            existing.state = ReviewState.RUNNING
            existing.pr_id = prRowId
            existing.sandbox_id = sandboxId
            existing.llm_provider = llmProvider
            existing.llm_model = llmModel
            existing.llm_base_url = llmBaseUrl
            existing.error_name = None
            existing.error_message = None
            existing.error_context = None
            if existing.started_at is None:
                existing.started_at = _utcnow()
            existing.updated_at = _utcnow()
            await session.commit()
            return ReviewRowId(existing.id)

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
            llm_model=llmModel,
            llm_base_url=llmBaseUrl,
            started_at=_utcnow(),
        )
        session.add(review)
        await session.commit()
        await session.refresh(review)
        return ReviewRowId(review.id)
    except Exception as exc:
        return LifecycleUpdateError(
            message=(
                f"mark running failed for workflow_id={workflowId} "
                f"repo_id={repo.id} pr_number={input.prNumber}: "
                f"{type(exc).__name__}: {exc}"
            ),
            userId=userId,
            repoId=repo.id,
            prNumber=input.prNumber,
            headSha=input.headSha,
        )


async def markReviewStopped(
    session: AsyncSession,
    *,
    reviewRowId: ReviewRowId,
    commentCount: int,
    githubReviewId: str | None,
    userId: UserId,
    repoId: RepoId,
) -> None | LifecycleUpdateError:
    """Flip the row to ``SUCCESS`` and persist the run outcome."""
    try:
        review = await session.get(Review, reviewRowId)
        if review is None:
            return LifecycleUpdateError(
                message=f"mark stopped: review {reviewRowId!r} not found",
                userId=userId,
                repoId=repoId,
            )
        review.state = ReviewState.SUCCESS
        review.comment_count = commentCount
        review.github_review_id = githubReviewId
        review.completed_at = _utcnow()
        review.updated_at = _utcnow()
        await session.commit()
        return None
    except Exception as exc:
        return LifecycleUpdateError(
            message=f"mark stopped failed for review_id={reviewRowId}: "
            f"{type(exc).__name__}: {exc}",
            userId=userId,
            repoId=repoId,
        )


async def markReviewErrored(
    session: AsyncSession,
    *,
    reviewRowId: ReviewRowId | None,
    errorName: str,
    errorMessage: str,
    errorContext: dict[str, Any] | None,
    userId: UserId,
    repoId: RepoId,
) -> None | LifecycleUpdateError:
    """Flip the row to ``FAILED`` and persist the typed error info.

    No-ops when ``reviewRowId`` is ``None`` — the workflow's ``except``
    block calls this even when the running step never completed.
    """
    if reviewRowId is None:
        return None
    try:
        review = await session.get(Review, reviewRowId)
        if review is None:
            return LifecycleUpdateError(
                message=f"mark errored: review {reviewRowId!r} not found",
                userId=userId,
                repoId=repoId,
            )
        review.state = ReviewState.FAILED
        review.error_name = errorName
        review.error_message = errorMessage
        review.error_context = errorContext
        review.completed_at = _utcnow()
        review.updated_at = _utcnow()
        await session.commit()
        return None
    except Exception as exc:
        return LifecycleUpdateError(
            message=f"mark errored failed for review_id={reviewRowId}: "
            f"{type(exc).__name__}: {exc}",
            userId=userId,
            repoId=repoId,
        )


def buildErrorContext(exc: BaseException) -> dict[str, Any] | None:
    """Project an exception onto the ``error_context`` JSONB shape.

    Full payload for :class:`ReviewAgentsError` (the dominant failure
    mode — both agent lanes exhausted their retries); ``None`` for
    everything else (the row keeps just ``error_name`` /
    ``error_message``). Wrapped step failures are unwrapped to their
    underlying error value first.
    """
    error = getattr(exc, "error", None)
    if isinstance(error, ReviewAgentsError):
        return {
            "error_name": ", ".join(type(f).__name__ for f in error.failedLanes)
            or type(error).__name__,
            "succeeded_agents": list(error.succeededLanes),
        }
    return None


@DBOS.step(
    retries_allowed=True,
    max_attempts=3,
    should_retry=shouldRetry,
    backoff_rate=2,
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
    llmModel: str,
    llmBaseUrl: str | None,
) -> ReviewRowId:
    """Durable step: find-or-create the ``RUNNING`` row for this run.

    Raises:
        TransientReviewStepFailure: the row could not be written (or
            the existing row could not be reset). DBOS retries up to 3
            attempts, then the workflow is ERROR.
    """
    async with async_session_maker() as session:
        result = await markReviewRunning(
            session,
            userId=userId,
            repo=repo,
            input=input,
            prRowId=prRowId,
            sandboxId=sandboxId,
            workflowId=workflowId,
            llmProvider=llmProvider,
            llmModel=llmModel,
            llmBaseUrl=llmBaseUrl,
        )
    if isinstance(result, LifecycleUpdateError):
        log.warning(
            "mark_review_is_running_step: failed workflow_id=%s repo_id=%s "
            "pr_number=%s cause=%s",
            workflowId,
            repo.id,
            input.prNumber,
            result.message,
        )
        raise TransientReviewStepFailure(result)
    log.info(
        "mark_review_is_running_step: ok review_id=%s workflow_id=%s "
        "repo_id=%s pr_number=%s",
        result,
        workflowId,
        repo.id,
        input.prNumber,
    )
    return result


@DBOS.step(
    retries_allowed=True,
    max_attempts=3,
    should_retry=shouldRetry,
    backoff_rate=2,
)
async def markReviewStoppedStep(
    *,
    reviewRowId: ReviewRowId,
    commentCount: int,
    githubReviewId: str | None,
    userId: UserId,
    repoId: RepoId,
) -> None:
    """Durable step: flip the row to ``SUCCESS``.

    Raises:
        TransientReviewStepFailure: the row could not be updated. DBOS
            retries up to 3 attempts; the workflow's ``except`` then
            flips the row to ``FAILED`` and re-raises.
    """
    async with async_session_maker() as session:
        result = await markReviewStopped(
            session,
            reviewRowId=reviewRowId,
            commentCount=commentCount,
            githubReviewId=githubReviewId,
            userId=userId,
            repoId=repoId,
        )
    if result is not None:
        log.warning(
            "mark_review_is_stopped_step: failed review_id=%s cause=%s",
            reviewRowId,
            result.message,
        )
        raise TransientReviewStepFailure(result)
    log.info(
        "mark_review_is_stopped_step: ok review_id=%s comments=%d "
        "github_review_id=%s",
        reviewRowId,
        commentCount,
        githubReviewId,
    )


@DBOS.step(
    retries_allowed=True,
    max_attempts=3,
    should_retry=shouldRetry,
    backoff_rate=2,
)
async def markReviewErroredStep(
    *,
    reviewRowId: ReviewRowId | None,
    errorName: str,
    errorMessage: str,
    errorContext: dict[str, Any] | None,
    userId: UserId,
    repoId: RepoId,
) -> None:
    """Durable step: flip the row to ``FAILED`` and persist the error.

    No-ops when ``reviewRowId`` is ``None``. The workflow wraps this
    call in its own try/except so a failure here never masks the
    original error.

    Raises:
        TransientReviewStepFailure: the row could not be updated.
    """
    async with async_session_maker() as session:
        result = await markReviewErrored(
            session,
            reviewRowId=reviewRowId,
            errorName=errorName,
            errorMessage=errorMessage,
            errorContext=errorContext,
            userId=userId,
            repoId=repoId,
        )
    if result is not None:
        log.warning(
            "mark_review_is_errored_step: failed review_id=%s cause=%s",
            reviewRowId,
            result.message,
        )
        raise TransientReviewStepFailure(result)
    log.info(
        "mark_review_is_errored_step: ok review_id=%s error=%s",
        reviewRowId,
        errorName,
    )


__all__ = [
    "buildErrorContext",
    "markReviewErrored",
    "markReviewErroredStep",
    "markReviewRunning",
    "markReviewRunningStep",
    "markReviewStopped",
    "markReviewStoppedStep",
]