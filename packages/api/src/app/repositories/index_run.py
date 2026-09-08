from __future__ import annotations

from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.indexing import IndexRun
from app.repositories.base import BaseRepository


class IndexRunRepository(BaseRepository[IndexRun]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(IndexRun, session)