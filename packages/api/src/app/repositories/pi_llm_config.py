from __future__ import annotations

from sqlmodel import col
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.pi_llm_config import LLMConfig
from app.repositories.base import BaseRepository


class PiLLMConfigRepository(BaseRepository[LLMConfig]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(LLMConfig, session)

    async def find_by_user(self, user_id: str) -> LLMConfig | None:
        """Return the user's stored pi config row, if any."""
        return await self.find(
            col(LLMConfig.user_id) == user_id,
            one=True,
        )
