from __future__ import annotations

from sqlmodel import col
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.llm_config import LLMConfigRecord
from app.repositories.base import BaseRepository


class LLMConfigRecordRepository(BaseRepository[LLMConfigRecord]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(LLMConfigRecord, session)

    async def find_by_user(self, user_id: str) -> LLMConfigRecord | None:
        """Return the user's stored config row, if any."""
        return await self.find(
            col(LLMConfigRecord.user_id) == user_id,
            one=True,
        )