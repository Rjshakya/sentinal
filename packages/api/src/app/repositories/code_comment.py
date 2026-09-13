from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import func
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.code_comment import CodeComment
from app.models.enums import CommentSeverity
from app.models.pull_request import PullRequest
from app.models.repo import Repo
from app.repositories.base import BaseRepository


class CodeCommentRepository(BaseRepository[CodeComment]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(CodeComment, session)

    async def find_by_review_id(
        self,
        review_id: str,
        *,
        order_by_created_at: bool = False,
    ) -> list[CodeComment]:
        """Return the comments of one review run."""
        if order_by_created_at:
            return await self.find(
                col(CodeComment.review_id) == review_id,
                order_by=col(CodeComment.created_at),
            )
        return await self.find(col(CodeComment.review_id) == review_id)

    async def find_by_ids(self, ids: Sequence[str]) -> list[CodeComment]:
        """Return every row whose primary key is in ``ids``."""
        return await self.find(col(CodeComment.id).in_(ids))

    async def count_for_user(self, user_id: str) -> int:
        """Count the user's comments, joined through repos."""
        stmt = (
            select(func.count())
            .select_from(CodeComment)
            .join(PullRequest)
            .join(Repo)
            .where(Repo.user_id == user_id)
        )
        result = await self.session.exec(stmt)
        return int(result.one() or 0)

    async def count_p1_for_user(self, user_id: str) -> int:
        """Count the user's ``P1_CRITICAL`` comments, joined through repos."""
        stmt = (
            select(func.count())
            .select_from(CodeComment)
            .join(PullRequest)
            .join(Repo)
            .where(
                Repo.user_id == user_id,
                CodeComment.severity == CommentSeverity.P1_CRITICAL.value,
            )
        )
        result = await self.session.exec(stmt)
        return int(result.one() or 0)
