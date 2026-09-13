from __future__ import annotations

from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.review_usage import ReviewUsage
from app.repositories.base import BaseRepository


class ReviewUsageRepository(BaseRepository[ReviewUsage]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(ReviewUsage, session)