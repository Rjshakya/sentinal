from __future__ import annotations

from sqlmodel import col
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.repo import Repo
from app.repositories.base import BaseRepository


class RepoRepository(BaseRepository[Repo]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(Repo, session)

    async def find_by_github_repo_id(self, github_repo_id: int) -> Repo | None:
        """Return the row for a GitHub repo id (globally unique)."""
        return await self.find(
            col(Repo.github_repo_id) == github_repo_id,
            one=True,
        )

    async def find_by_owner_name(
        self,
        user_id: str,
        repo_owner: str,
        repo_name: str,
    ) -> Repo | None:
        """Return the user's row for one ``owner/name`` pair."""
        return await self.find(
            col(Repo.user_id) == user_id,
            col(Repo.repo_owner) == repo_owner,
            col(Repo.repo_name) == repo_name,
            one=True,
        )
