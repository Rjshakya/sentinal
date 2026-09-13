from __future__ import annotations

from sqlalchemy import func
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.pull_request import PullRequest
from app.models.repo import Repo
from app.models.review_summary import ReviewSummary
from app.repositories.base import BaseRepository


class ReviewSummaryRepository(BaseRepository[ReviewSummary]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(ReviewSummary, session)

    async def find_by_review_id(self, review_id: str) -> ReviewSummary | None:
        """Return the summary attached to one review run."""
        return await self.find(
            col(ReviewSummary.review_id) == review_id,
            one=True,
        )

    async def count_for_user(self, user_id: str) -> int:
        """Count the user's review summaries, joined through repos."""
        stmt = (
            select(func.count())
            .select_from(ReviewSummary)
            .join(PullRequest)
            .join(Repo)
            .where(Repo.user_id == user_id)
        )
        result = await self.session.exec(stmt)
        return int(result.one() or 0)