from __future__ import annotations

from sqlmodel import col
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.indexing import IndexRun
from app.repositories.base import BaseRepository


class IndexRunRepository(BaseRepository[IndexRun]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(IndexRun, session)

    async def find_by_workflow_id(self, workflow_id: str) -> IndexRun | None:
        """Return the mirror row for a deterministic indexing workflow id."""
        return await self.find(
            col(IndexRun.workflow_id) == workflow_id,
            one=True,
        )
