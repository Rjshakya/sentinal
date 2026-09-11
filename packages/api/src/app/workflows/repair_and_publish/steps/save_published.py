"""Save the publish outcome after the repair agent posts.

Downstream of :class:`app.workflows.repair_and_publish.types.PublishedReview`:

- **posted comments** stay in the DB and get their ``review_id``
  written explicitly (the lifecycle row of the run — idempotent: the
  rows already carry it from the original persist).
- **left comments** (never posted: dropped by the agent or invalid
  after the retry budget) are **deleted** from the DB entirely, so they
  never get re-picked by a future check.

The summary review back-links (``review.github_review_id`` /
``review_summaries.github_review_id``) are owned by the manual summary
step that runs before the repair step, not here.

- :func:`persistPublishedReview` — the **value-returning** worker.
- :func:`savePublishedReview` — the **DBOS-wrapped** transaction edge
  that raises :class:`RepairPublishStepFailure` on failure.
"""

from __future__ import annotations

from dbos import DBOS
from sqlmodel import col
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.db import async_session_maker
from app.models.code_comment import CodeComment
from app.repositories.code_comment import CodeCommentRepository
from app.repositories.review import ReviewRepository
from app.repositories.review_summary import ReviewSummaryRepository
from app.workflows.repair_and_publish.errors import (
    RepairPublishStepFailure,
    SaveError,
)
from app.workflows.repair_and_publish.types import (
    PublishedReview,
    UnpublishedReview,
)


async def savePublishedReview(
    *,
    session: AsyncSession,
    unpublished: UnpublishedReview,
    published: PublishedReview,
):

    try:
        reviews = ReviewRepository(session=session)
        review = await reviews.get(unpublished.reviewId)

        if review is None:
            return None

        review.github_review_id = str(published.githubReviewId)

        if published.postedComments:
            review.comment_count = len(published.postedComments)

        await reviews.add(review)

        summaries = ReviewSummaryRepository(session=session)
        summary = await summaries.find_by_review_id(unpublished.reviewId)

        if summary is None:
            return None

        summary.github_review_id = str(published.githubReviewId)
        await summaries.add(summary)

        comments = CodeCommentRepository(session=session)
        if published.postedComments:
            rows = await comments.find_by_ids(
                [row.commentId for row in published.postedComments]
            )
            for row in rows:
                row.github_review_id = unpublished.reviewId
                await comments.add(row)

        if published.leftComments:
            await comments.delete(
                col(CodeComment.id).in_(
                    [row.commentId for row in published.leftComments]
                )
            )

        await session.commit()

    except Exception as exc:
        return SaveError(
            message=f"failed to save publish outcome: {type(exc).__name__}: {exc}",
            reviewId=unpublished.reviewId,
            repoId=unpublished.repoId,
            prNumber=unpublished.prNumber,
        )


@DBOS.step()
async def savePublishedReviewStep(
    *,
    unpublished: UnpublishedReview,
    published: PublishedReview,
) -> None:
    """Durable DBOS transaction: persist the publish outcome.

    Raises:
        RepairPublishStepFailure: the rows could not be written
            (wrapping a :class:`SaveError`).
    """
    async with async_session_maker() as session:
        result = await savePublishedReview(
            session=session,
            unpublished=unpublished,
            published=published,
        )
        if result is not None:
            raise RepairPublishStepFailure(result)


__all__ = ["savePublishedReviewStep"]
