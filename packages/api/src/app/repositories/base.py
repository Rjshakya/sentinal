from __future__ import annotations

from typing import Any, Generic, Type, TypeVar, cast

from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute
from sqlalchemy.sql.elements import ColumnElement
from sqlmodel import SQLModel, delete, select, update

T = TypeVar("T", bound=SQLModel)
C = TypeVar("C")


class Repository(Generic[T]):
    def __init__(self, model: Type[T], session: AsyncSession) -> None:
        self._model = model
        self._session = session

    async def get(self, id: Any) -> T | None:
        return await self._session.get(self._model, id)

    async def all(self, *, limit: int | None = None) -> list[T]:
        stmt = select(self._model)
        if limit is not None:
            stmt = stmt.limit(limit)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def find_by_field(
        self, col: InstrumentedAttribute[C] | C, value: C
    ) -> T | None:
        stmt = select(self._model).where(cast(ColumnElement[bool], col == value))
        result = await self._session.execute(stmt)
        return result.scalars().first()

    async def find_all_by_field(
        self,
        col: InstrumentedAttribute[C] | C,
        value: C,
        *,
        limit: int | None = None,
    ) -> list[T]:
        stmt = select(self._model).where(cast(ColumnElement[bool], col == value))
        if limit is not None:
            stmt = stmt.limit(limit)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def find_by_fields(self, **fields: Any) -> T | None:
        """Look up a single row matching every ``field=value`` keyword arg.

        Issues a single ``SELECT ... WHERE col1 = ? AND col2 = ? ...``
        (one round-trip, not one query per field — i.e. **not** an N+1).
        Returns the first matching row, or ``None`` if nothing matches.
        """
        stmt = select(self._model)
        for attr, value in fields.items():
            stmt = stmt.where(getattr(self._model, attr) == value)
        result = await self._session.execute(stmt)
        return result.scalars().first()

    async def add(self, obj: T) -> T:
        self._session.add(obj)
        return obj

    async def update_by_field(
        self,
        col: InstrumentedAttribute[C] | C,
        value: C,
        **updates: Any,
    ) -> T | None:
        stmt = (
            update(self._model)
            .where(cast(ColumnElement[bool], col == value))
            .values(**updates)
        )
        await self._session.execute(stmt)
        return await self.find_by_field(col, value)

    async def delete(self, col: InstrumentedAttribute[C] | C, value: C) -> bool:
        stmt = delete(self._model).where(cast(ColumnElement[bool], col == value))
        result = cast(CursorResult[Any], await self._session.execute(stmt))
        return (result.rowcount or 0) > 0


def make_repo(model: Type[T], session: AsyncSession) -> Repository[T]:
    return Repository(model, session)
