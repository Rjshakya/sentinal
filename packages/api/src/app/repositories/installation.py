from __future__ import annotations

from sqlalchemy import ColumnElement
from sqlmodel import col
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.installation import Installation
from app.repositories.base import BaseRepository


class InstallationRepository(BaseRepository[Installation]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(Installation, session)

    async def find_by_github_installation_id(
        self, github_installation_id: int
    ) -> Installation | None:
        """Return the row for a GitHub installation id (globally unique)."""
        return await self.find(
            col(Installation.github_installation_id) == github_installation_id,
            one=True,
        )

    async def find_by_user(self, user_id: str) -> list[Installation]:
        """Return the user's installations, newest first."""
        return await self.find(
            col(Installation.user_id) == user_id,
            order_by=col(Installation.created_at).asc(),
        )

    async def find_by_user_and_login(
        self,
        user_id: str,
        account_login: str,
        *,
        active_only: bool = False,
    ) -> Installation | None:
        """Return the user's installation for ``account_login``.

        ``active_only`` also requires ``suspended_at IS NULL``.
        """
        conditions: list[ColumnElement[bool]] = [
            col(Installation.user_id) == user_id,
            col(Installation.account_login) == account_login,
        ]
        if active_only:
            conditions.append(col(Installation.suspended_at).is_(None))
        return await self.find(*conditions, one=True)
