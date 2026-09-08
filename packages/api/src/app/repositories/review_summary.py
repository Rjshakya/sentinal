from __future__ import annotations

from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.review_summary import ReviewSummary
from app.repositories.base import BaseRepository


class ReviewSummaryRepository(BaseRepository[ReviewSummary]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(ReviewSummary, session)