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
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.util import await_fallback
from sqlmodel import select

from app.core.db import async_session_maker
from app.models.code_comment import CodeComment
from app.models.review import Review
from app.models.review_summary import ReviewSummary
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
        q = select(Review).where(Review.id == unpublished.reviewId)
        review = (await session.execute(q)).scalars().first()

        if review is None:
            return None

        review.github_review_id = str(published.githubReviewId)
        session.add(review)

        q = select(ReviewSummary).where(ReviewSummary.review_id == unpublished.reviewId)
        summary = (await session.execute(q)).scalars().first()

        if summary is None:
            return None

        summary.github_review_id = str(published.githubReviewId)
        session.add(summary)

        if published.postedComments:
            rows = (
                (
                    await session.execute(
                        select(CodeComment).where(
                            CodeComment.id.in_(  # type: ignore[attr-defined]
                                [row.commentId for row in published.postedComments]
                            )
                        )
                    )
                )
                .scalars()
                .all()
            )
            for row in rows:
                row.github_review_id = unpublished.reviewId
                session.add(row)

        if published.leftComments:
            await session.execute(
                delete(CodeComment).where(
                    CodeComment.id.in_(  # type: ignore[attr-defined]
                        [row.commentId for row in published.leftComments]
                    )
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
