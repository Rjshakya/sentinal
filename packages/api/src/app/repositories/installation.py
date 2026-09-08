from __future__ import annotations

from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.installation import Installation
from app.repositories.base import BaseRepository


class InstallationRepository(BaseRepository[Installation]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(Installation, session)