"""Step: resolve the latest successful ``review`` row for a PR.

The ``issue_comment`` trigger can run an **incremental re-review**:
when the PR head moved since the last successful review, the inner
``review_workflow`` diffs only the commits between the last reviewed
head and the new head instead of the full PR diff. This step loads
the previous run's record so the trigger workflow can decide the
git-diff base.

Two layers in this module, following the Functional Core / Imperative
Shell split:

- :func:`_load_last_review` — the **pure** helper. Takes a session,
  a local ``repo_id`` and a ``pr_number``, returns the newest
  ``SUCCESS`` :class:`app.models.review.Review` row (or ``None``) as
  a :class:`app.services.pr_issue_comment.types.LastReviewSnapshot`.
  No DBOS.
- :func:`resolve_last_review_step` — the **DBOS-wrapped** step. Opens
  its own session and runs the same lookup. The snapshot is the
  serialisable subset DBOS can persist across the workflow boundary.
"""

from __future__ import annotations

import logging

from dbos import DBOS
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.core.db import async_session_maker
from app.models.review import Review, ReviewState
from app.services.pr_issue_comment.types import LastReviewSnapshot

log = logging.getLogger(__name__)


async def _load_last_review(
    session: AsyncSession,
    *,
    repo_id: str,
    pr_number: int,
) -> LastReviewSnapshot | None:
    """Fetch the latest ``SUCCESS`` ``review`` row for the PR.

    The lookup is scoped to ``(repo_id, pr_number)`` — the same key
    the review lifecycle rows are written with — and ordered newest
    first so a force-pushed PR still resolves to its most recent
    successful run.
    """
    stmt = (
        select(Review)
        .where(
            Review.repo_id == repo_id,
            Review.pr_number == pr_number,
            Review.state == ReviewState.SUCCESS,
        )
        .order_by(Review.created_at.desc())
        .limit(1)
    )
    result = await session.exec(stmt)
    row = result.first()
    if row is None:
        return None
    return LastReviewSnapshot(
        commit_id=row.commit_id,
        base_sha=row.base_sha,
        created_at=row.created_at,
    )


@DBOS.step()
async def resolve_last_review_step(
    repo_id: str,
    pr_number: int,
) -> LastReviewSnapshot | None:
    """Durable DBOS step: load the latest successful review snapshot.

    Returns ``None`` when the PR has never completed a review — the
    trigger workflow then falls back to the GitHub API's ``base_sha``
    (first-review behaviour). The snapshot only carries ``commit_id`` /
    ``base_sha`` / ``created_at``; DBOS cannot persist the ORM row
    across the step boundary.
    """
    async with async_session_maker() as session:
        snapshot = await _load_last_review(
            session,
            repo_id=repo_id,
            pr_number=pr_number,
        )

    if snapshot is None:
        log.info(
            "pr_issue_comment.resolve_last_review_step: no prior "
            "successful review: repo_id=%s pr_number=%s",
            repo_id,
            pr_number,
        )
    else:
        log.info(
            "pr_issue_comment.resolve_last_review_step: found prior "
            "review: repo_id=%s pr_number=%s commit_id=%s created_at=%s",
            repo_id,
            pr_number,
            snapshot.commit_id,
            snapshot.created_at,
        )
    return snapshot


__all__ = ["resolve_last_review_step"]