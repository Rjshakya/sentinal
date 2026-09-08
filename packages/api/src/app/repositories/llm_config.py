from __future__ import annotations

from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.llm_config import LLMConfigRecord
from app.repositories.base import BaseRepository


class LLMConfigRecordRepository(BaseRepository[LLMConfigRecord]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(LLMConfigRecord, session)