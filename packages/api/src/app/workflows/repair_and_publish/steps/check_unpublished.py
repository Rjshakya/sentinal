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
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, select

from app.core.db import async_session_maker
from app.models.code_comment import CodeComment
from app.models.enums import CommentState
from app.models.installation import Installation
from app.models.repo import Repo
from app.models.review import Review
from app.models.review_summary import ReviewSummary
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
        review = (
            (
                await session.execute(
                    select(Review).where(
                        Review.commit_id == commitId,
                        col(Review.github_review_id).is_(None),
                    )
                )
            )
            .scalars()
            .first()
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
        summary = (
            (
                await session.execute(
                    select(ReviewSummary).where(
                        ReviewSummary.review_id == reviewId,
                        col(ReviewSummary.github_review_id).is_(None),
                    )
                )
            )
            .scalars()
            .first()
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
        comment_rows = (
            (
                await session.execute(
                    select(CodeComment)
                    .where(
                        CodeComment.review_id == reviewId,
                        col(CodeComment.github_review_id).is_(None),
                    )
                    .order_by(col(CodeComment.created_at))
                )
            )
            .scalars()
            .all()
        )
        repo = (
            (await session.execute(select(Repo).where(Repo.id == review.repo_id)))
            .scalars()
            .first()
        )
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
        installation = (
            (
                await session.execute(
                    select(Installation).where(
                        Installation.user_id == review.user_id,
                        Installation.account_login == repo.repo_owner,
                        Installation.suspended_at.is_(None),  # type: ignore[union-attr]
                    )
                )
            )
            .scalars()
            .first()
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
