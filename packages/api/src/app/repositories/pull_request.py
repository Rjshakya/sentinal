from __future__ import annotations

from sqlmodel import col
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.pull_request import PullRequest
from app.repositories.base import BaseRepository


class PullRequestRepository(BaseRepository[PullRequest]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(PullRequest, session)

    async def find_by_repo_and_number(
        self,
        repo_id: str,
        number: int,
    ) -> PullRequest | None:
        """Return the local row for one PR number on one repo."""
        return await self.find(
            col(PullRequest.repo_id) == repo_id,
            col(PullRequest.number) == number,
            one=True,
        )