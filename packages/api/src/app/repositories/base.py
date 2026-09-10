from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Generic, List, Literal, TypeVar, overload

from sqlalchemy import (
    Column,
    ColumnElement,
    ColumnExpressionArgument,
    func,
)
from sqlalchemy import exists as sa_exists
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Mapped
from sqlmodel import SQLModel, delete, select, update
from sqlmodel.ext.asyncio.session import AsyncSession

T = TypeVar("T", bound=SQLModel)

OrderByArg = ColumnExpressionArgument[Any] | Sequence[ColumnExpressionArgument[Any]]


class BaseRepository(Generic[T]):
    """Generic async data-access helper bound to one SQLModel table.

    The base stays model-agnostic: reads are expressed as SQLAlchemy
    boolean expressions passed to :meth:`find` / :meth:`count` /
    :meth:`exists`, so every operator works without per-model code::

        await repo.find(col(repo.model.user_id) == user_id, one=True)
        await repo.find(col(repo.model.github_repo_id).in_(ids))
        await repo.find(col(repo.model.suspended_at).is_(None))

    Use :func:`sqlmodel.col` to build the conditions: plain model
    attributes are typed as their column annotation, while ``col(...)``
    yields a typed expression whose comparisons return
    ``ColumnElement[bool]``. Reference columns through the
    repository's :attr:`model` (``repo.model.<column>``) so call sites
    do not import the model class for queries.

    Anything the base cannot express — joins, column projections,
    multi-table aggregates — goes through the public
    :attr:`session` / :attr:`model` attributes::

        repo = RepoRepository(session)
        rows = await repo.session.exec(select(repo.model).where(...))

    Repositories never commit; the caller owns the transaction.
    """

    def __init__(self, model: type[T], session: AsyncSession) -> None:
        self.model = model
        self.session = session

    async def get(self, id: Any) -> T | None:
        """Return the row with primary key ``id``, or ``None``."""
        return await self.session.get(self.model, id)

    @overload
    async def find(
        self,
        *conditions: ColumnElement[bool],
        order_by: OrderByArg | None = None,
        limit: int | None = None,
        offset: int | None = None,
        one: Literal[True],
    ) -> T | None: ...

    @overload
    async def find(
        self,
        *conditions: ColumnElement[bool],
        order_by: OrderByArg | None = None,
        limit: int | None = None,
        offset: int | None = None,
        one: Literal[False] = False,
    ) -> list[T]: ...

    async def find(
        self,
        *conditions: ColumnElement[bool],
        order_by: OrderByArg | None = None,
        limit: int | None = None,
        offset: int | None = None,
        one: bool = False,
    ) -> list[T] | T | None:
        """Read every row matching all ``conditions``.

        ``conditions`` are SQLAlchemy boolean expressions over this
        repository's model. ``order_by`` accepts a single expression
        (e.g. ``col(Model.created_at).desc()``) or a sequence of them.
        With ``one=True`` the first matching row is returned
        (``T | None``); otherwise the matching rows are returned as a
        list.
        """
        stmt = select(self.model)
        if conditions:
            stmt = stmt.where(*conditions)
        if order_by is not None:
            if isinstance(order_by, Sequence):
                stmt = stmt.order_by(*order_by)
            else:
                stmt = stmt.order_by(order_by)
        if limit is not None:
            stmt = stmt.limit(limit)
        if offset is not None:
            stmt = stmt.offset(offset)

        result = await self.session.exec(stmt)
        if one:
            return result.first()
        return list(result.all())

    async def count(self, *conditions: ColumnElement[bool]) -> int:
        """Return the number of rows matching all ``conditions``."""
        stmt = select(func.count()).select_from(self.model)
        if conditions:
            stmt = stmt.where(*conditions)
        result = await self.session.exec(stmt)
        return int(result.one())

    async def exists(self, *conditions: ColumnElement[bool]) -> bool:
        """Return whether at least one row matches all ``conditions``."""
        stmt = select(sa_exists().where(*conditions))
        result = await self.session.exec(stmt)
        return bool(result.one())

    async def add(self, obj: T) -> T:
        """Stage ``obj`` on the session; the caller commits."""
        self.session.add(obj)
        return obj

    async def update(
        self,
        *conditions: ColumnElement[bool],
        values: T,
    ) -> list[T]:
        """Update every row matching all ``conditions`` and return them.

        Only the fields explicitly set on ``values`` are written
        (``exclude_unset``), so ``default_factory`` fields such as
        ``id`` / ``created_at`` are left untouched unless the caller
        set them. Requires at least one condition so a stray call
        cannot rewrite the whole table. The caller owns the commit.
        """
        if not conditions:
            raise ValueError("update() requires at least one condition")
        stmt = (
            update(self.model)
            .where(*conditions)
            .values(values.model_dump(exclude_unset=True))
            .returning(self.model)
        )
        result = await self.session.exec(stmt)
        updated: list[T] = list(result.scalars().all())
        await self.session.flush()
        return updated

    async def upsert(
        self,
        values: T,
        *,
        conflict_on: List[Mapped[Any]],
    ) -> T:
        """Insert ``values``; on conflict update every given field.

        Postgres ``INSERT ... ON CONFLICT DO UPDATE``. ``conflict_on``
        is the unique key the conflict is detected on; ``created_at``
        is preserved on update. Returns the persisted row. The caller
        owns the commit.
        """

        stmt = (
            pg_insert(self.model)
            .values(values.model_dump())
            .on_conflict_do_update(
                index_elements=list(conflict_on),
                set_={
                    k: v
                    for k, v in values.model_dump(exclude_unset=True).items()
                    if k != "created_at"
                },
            )
            .returning(self.model)
        )
        result = await self.session.execute(
            stmt,
            execution_options={"populate_existing": True},
        )
        row: T = result.scalars().one()
        return row

    async def delete(self, *conditions: ColumnElement[bool]) -> list[T]:
        """Delete every row matching all ``conditions`` and return them.

        Requires at least one condition so a stray call cannot wipe the
        table. The caller owns the commit.
        """
        if not conditions:
            raise ValueError("delete() requires at least one condition")
        stmt = delete(self.model).where(*conditions).returning(self.model)
        result = await self.session.execute(stmt)
        deleted = list(result.scalars().all())
        await self.session.flush()
        return deleted


__all__ = ["BaseRepository", "OrderByArg"]
