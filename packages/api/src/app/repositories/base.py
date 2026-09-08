from __future__ import annotations

from typing import Any, Generic, Sequence, TypeVar, cast

from sqlalchemy import Row
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import InstrumentedAttribute
from sqlalchemy.sql.elements import ColumnElement
from sqlmodel import SQLModel, col, delete, select, update
from sqlmodel.ext.asyncio.session import AsyncSession

T = TypeVar("T", bound=SQLModel)
C = TypeVar("C")


class BaseRepository(Generic[T]):
    def __init__(self, model: type[T], session: AsyncSession) -> None:
        self._model = model
        self._session = session

    async def get(self, id: Any) -> T | None:
        return await self._session.get(self._model, id)

    async def all(self, *, limit: int | None = None) -> list[T]:
        stmt = select(self._model)
        if limit is not None:
            stmt = stmt.limit(limit)

        result = await self._session.exec(stmt)
        return list(result.all())

    async def findByField(self, column: C, value: C) -> T | None:
        stmt = select(self._model).where(col(column) == value)
        result = await self._session.exec(stmt)
        return result.first()

    async def findAllByField(
        self,
        column: C,
        value: C,
        *,
        limit: int | None = None,
    ) -> list[T]:
        stmt = select(self._model).where(col(column) == value)
        if limit is not None:
            stmt = stmt.limit(limit)
        result = await self._session.exec(stmt)
        return list(result.all())

    async def add(self, obj: T) -> T:
        self._session.add(obj)
        return obj

    async def delete(self, column: C, value: C) -> T | None:
        stmt = delete(self._model).where(col(column) == value).returning(self._model)
        result = await self._session.execute(stmt)
        deleted = result.scalars().one_or_none()
        await self._session.flush()
        return deleted


def makeRepo(model: type[T], session: AsyncSession) -> BaseRepository[T]:
    return BaseRepository(model, session)
