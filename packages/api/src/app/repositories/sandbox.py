from __future__ import annotations

from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.sandbox import Sandbox
from app.repositories.base import BaseRepository


class SandboxRepository(BaseRepository[Sandbox]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(Sandbox, session)