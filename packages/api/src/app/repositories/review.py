from __future__ import annotations

from sqlmodel import col
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.review import Review, ReviewState
from app.repositories.base import BaseRepository


class ReviewRepository(BaseRepository[Review]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(Review, session)

    async def find_by_workflow_id(self, workflow_id: str) -> Review | None:
        """Return the lifecycle row for a deterministic workflow id."""
        return await self.find(
            col(Review.workflow_id) == workflow_id,
            one=True,
        )

    async def find_latest_success(
        self,
        repo_id: str,
        pr_number: int,
    ) -> Review | None:
        """Return the newest ``SUCCESS`` row for one PR, or ``None``."""
        return await self.find(
            col(Review.repo_id) == repo_id,
            col(Review.pr_number) == pr_number,
            col(Review.state) == ReviewState.SUCCESS,
            order_by=col(Review.created_at).desc(),
            one=True,
        )