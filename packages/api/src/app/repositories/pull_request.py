from __future__ import annotations

from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.pull_request import PullRequest
from app.repositories.base import BaseRepository


class PullRequestRepository(BaseRepository[PullRequest]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(PullRequest, session)