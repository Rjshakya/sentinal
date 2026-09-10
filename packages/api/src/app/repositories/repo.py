from __future__ import annotations

from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.repo import Repo
from app.repositories.base import BaseRepository


class RepoRepository(BaseRepository[Repo]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(Repo, session)
