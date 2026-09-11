"""Check whether an unpublished review exists for a review run.

Two layers, following the new service conventions:

- :func:`loadUnpublishedReview` — the **value-returning** worker. Takes
  the caller's :class:`AsyncSession` and the review row id, returns an
  :class:`UnpublishedReview`, ``None`` (no unpublished review — the
  workflow's never-run conditions: no ``review`` row, no summary for
  the run, or a summary that already carries a ``github_review_id``),
  or a :class:`CheckError` value. No DBOS, no raising.
- :func:`checkUnpublishedReviewExist` — the **DBOS-wrapped** step edge.
  Acquires a session, calls the worker, and raises
  :class:`TransientRepairPublishStepFailure` / :class:`RepairPublishStepFailure`
  for the error cases so DBOS handles them; ``None`` travels back to
  the workflow as a business skip.
"""

from __future__ import annotations

from typing import cast

from dbos import DBOS
from sqlmodel import col
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.db import async_session_maker
from app.models.code_comment import CodeComment
from app.models.enums import CommentState
from app.models.review import Review
from app.models.review_summary import ReviewSummary
from app.repositories.code_comment import CodeCommentRepository
from app.repositories.installation import InstallationRepository
from app.repositories.repo import RepoRepository
from app.repositories.review import ReviewRepository
from app.repositories.review_summary import ReviewSummaryRepository
from app.utils.branded import (
    CommitId,
    InstallationId,
    PRNumber,
    RepoId,
    RepoName,
    RepoOwner,
    ReviewRowId,
    UserId,
)
from app.utils.schema import (
    CommentSeverityStr,
    CommentSideStr,
    ReviewVerdictStr,
)
from app.workflows.repair_and_publish.errors import (
    CheckError,
    RepairPublishStepFailure,
    TransientRepairPublishStepFailure,
)
from app.workflows.repair_and_publish.types import CommentRow, UnpublishedReview


def _checkError(
    message: str,
    *,
    reviewId: ReviewRowId | None = None,
    commitId: str | None = None,
    retryable: bool = False,
) -> CheckError:
    return CheckError(
        message=message,
        retryable=retryable,
        reviewId=reviewId,
    )


async def loadUnpublishedReview(
    session: AsyncSession,
    *,
    commitId: str,
) -> UnpublishedReview | None | CheckError:
    """Load the publish data for a review run.

    Returns:
        :class:`UnpublishedReview` when the run is publishable;
        ``None`` when no unpublished review exists (no review row, no
        summary, or the summary already carries a ``github_review_id``
        — business skips); a :class:`CheckError` for DB / config
        problems. Never raises.
    """
    try:
        reviews = ReviewRepository(session=session)
        review = await reviews.find(
            col(Review.commit_id) == commitId,
            col(Review.github_review_id).is_(None),
            one=True,
        )
    except Exception as exc:
        return _checkError(
            f"failed to load review row: {type(exc).__name__}: {exc}",
            commitId=commitId,
            retryable=True,
        )
    if review is None:
        return None

    reviewId = ReviewRowId(review.id)

    try:
        summaries = ReviewSummaryRepository(session=session)
        summary = await summaries.find(
            col(ReviewSummary.review_id) == reviewId,
            col(ReviewSummary.github_review_id).is_(None),
            one=True,
        )
    except Exception as exc:
        return _checkError(
            f"failed to load review summary: {type(exc).__name__}: {exc}",
            reviewId=reviewId,
            retryable=True,
        )
    if summary is None:
        return None
    if summary.github_review_id is not None:
        return None

    try:
        comments_repo = CodeCommentRepository(session=session)
        comment_rows = await comments_repo.find(
            col(CodeComment.review_id) == reviewId,
            col(CodeComment.github_review_id).is_(None),
            order_by=col(CodeComment.created_at),
        )
        repo = await RepoRepository(session=session).get(review.repo_id)
    except Exception as exc:
        return _checkError(
            f"failed to load comments / repo: {type(exc).__name__}: {exc}",
            reviewId=reviewId,
            retryable=True,
        )
    if repo is None:
        return _checkError(
            f"no repo row for review {reviewId!r} (repo_id={review.repo_id!r})",
            reviewId=reviewId,
        )

    try:
        installation = await InstallationRepository(
            session=session
        ).find_by_user_and_login(
            review.user_id,
            repo.repo_owner,
            active_only=True,
        )
    except Exception as exc:
        return _checkError(
            f"failed to resolve installation: {type(exc).__name__}: {exc}",
            reviewId=reviewId,
            retryable=True,
        )
    if installation is None:
        return _checkError(
            f"no installation for user {review.user_id!r} / owner "
            f"{repo.repo_owner!r}",
            reviewId=reviewId,
        )

    comments: list[CommentRow] = []
    for row in comment_rows:
        comments.append(
            CommentRow(
                commentId=row.id,
                fileName=row.file_name,
                fromLine=row.from_line,
                toLine=row.to_line,
                side=cast(CommentSideStr, row.side.value),
                severity=cast(CommentSeverityStr, row.severity.value),
                body=row.comment,
                nodeType=row.node_type,
            )
        )

    return UnpublishedReview(
        reviewId=ReviewRowId(review.id),
        userId=UserId(review.user_id),
        repoId=RepoId(review.repo_id),
        prNumber=PRNumber(review.pr_number),
        commitId=CommitId(review.commit_id),
        baseSha=review.base_sha,
        repoOwner=RepoOwner(repo.repo_owner),
        repoName=RepoName(repo.repo_name),
        installationId=InstallationId(installation.github_installation_id),
        summary=summary.summary,
        verdict=cast(ReviewVerdictStr, summary.verdict.value),
        comments=comments,
    )


@DBOS.step()
async def checkUnpublishedReviewExist(*, commitId: str) -> UnpublishedReview | None:
    """Durable step: check for an unpublished review of a review run.

    Raises:
        TransientRepairPublishStepFailure: a retryable (DB) check
            failure — DBOS retries the step.
        RepairPublishStepFailure: a config problem (no repo row, no
            installation) — business outcome.
    Returns:
        The :class:`UnpublishedReview` when the run is publishable, or
        ``None`` when no unpublished review exists (business skip —
        the workflow completes without posting).
    """
    async with async_session_maker() as session:
        result = await loadUnpublishedReview(session, commitId=commitId)
    if isinstance(result, CheckError):
        if result.retryable:
            raise TransientRepairPublishStepFailure(result)
        raise RepairPublishStepFailure(result)
    return result


__all__ = ["checkUnpublishedReviewExist", "loadUnpublishedReview"]
