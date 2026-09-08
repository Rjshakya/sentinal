from __future__ import annotations

from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.code_comment import CodeComment
from app.repositories.base import BaseRepository


class CodeCommentRepository(BaseRepository[CodeComment]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(CodeComment, session)