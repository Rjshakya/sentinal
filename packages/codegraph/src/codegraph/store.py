"""Async persistence for the code graph.

All I/O here is async end-to-end (``aiosqlite`` / ``asyncpg`` drivers).
Callers never touch the engine directly beyond :func:`create_store`.
"""

from __future__ import annotations

import enum
from collections.abc import Sequence

from sqlalchemy import delete, func
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool
from sqlmodel import SQLModel, col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from codegraph.models import Edge, EdgeKind, Node, NodeKind


class GraphStore:
    """Owns the async engine and session factory for one database."""

    def __init__(self, url: str) -> None:
        # SQLite (aiosqlite) runs its connection on a dedicated worker
        # thread; pooled connections racing the GC segfault on Windows
        # (access violation in the worker thread). The CLI is strictly
        # sequential, so pooling buys nothing — open/close per checkout.
        # Postgres keeps the default pool.
        if url.startswith("sqlite"):
            self._engine: AsyncEngine = create_async_engine(
                url, future=True, poolclass=NullPool
            )
        else:
            self._engine = create_async_engine(url, future=True)
        self._sessions: async_sessionmaker[AsyncSession] = async_sessionmaker(
            self._engine, class_=AsyncSession, expire_on_commit=False
        )

    @property
    def engine(self) -> AsyncEngine:
        """Return the underlying async engine."""
        return self._engine

    async def create_all(self) -> None:
        """Create tables when they do not exist yet."""
        async with self._engine.begin() as conn:
            await conn.run_sync(SQLModel.metadata.create_all)

    async def clear_root(self, root: str) -> None:
        """Delete every node/edge previously indexed under ``root``."""
        async with self._sessions() as session:
            await session.exec(delete(Edge).where(col(Edge.root) == root))
            await session.exec(delete(Node).where(col(Node.root) == root))
            await session.commit()

    async def add_all(self, nodes: Sequence[Node], edges: Sequence[Edge]) -> None:
        """Bulk-insert one batch of nodes plus their edges."""
        if not nodes and not edges:
            return
        async with self._sessions() as session:
            session.add_all(list(nodes))
            session.add_all(list(edges))
            await session.commit()

    async def count_by_node_kind(self, root: str | None = None) -> dict[str, int]:
        """Return row counts grouped by node kind (keys are kind values)."""
        async with self._sessions() as session:
            stmt = select(col(Node.kind), func.count()).group_by(col(Node.kind))
            if root is not None:
                stmt = stmt.where(col(Node.root) == root)
            rows = (await session.exec(stmt)).all()
            return {_enum_value(kind): int(count) for kind, count in rows}

    async def count_by_edge_kind(self, root: str | None = None) -> dict[str, int]:
        """Return row counts grouped by edge kind (keys are kind values)."""
        async with self._sessions() as session:
            stmt = select(col(Edge.kind), func.count()).group_by(col(Edge.kind))
            if root is not None:
                stmt = stmt.where(col(Edge.root) == root)
            rows = (await session.exec(stmt)).all()
            return {_enum_value(kind): int(count) for kind, count in rows}

    async def count_by_language(self, root: str | None = None) -> dict[str, int]:
        """Return file-node counts grouped by language."""
        async with self._sessions() as session:
            stmt = (
                select(col(Node.language), func.count())
                .where(col(Node.kind) == NodeKind.FILE)
                .group_by(col(Node.language))
            )
            if root is not None:
                stmt = stmt.where(col(Node.root) == root)
            rows = (await session.exec(stmt)).all()
            return {str(lang): int(count) for lang, count in rows}

    async def total_counts(self, root: str | None = None) -> tuple[int, int, int]:
        """Return ``(files, nodes, edges)`` totals."""
        async with self._sessions() as session:
            file_stmt = select(func.count()).select_from(Node).where(
                col(Node.kind) == NodeKind.FILE
            )
            node_stmt = select(func.count()).select_from(Node)
            edge_stmt = select(func.count()).select_from(Edge)
            if root is not None:
                file_stmt = file_stmt.where(col(Node.root) == root)
                node_stmt = node_stmt.where(col(Node.root) == root)
                edge_stmt = edge_stmt.where(col(Edge.root) == root)
            files = int((await session.exec(file_stmt)).one())
            nodes = int((await session.exec(node_stmt)).one())
            edges = int((await session.exec(edge_stmt)).one())
            return (files, nodes, edges)

    async def top_importers(self, limit: int = 10) -> list[tuple[str, int]]:
        """Return ``(file_path, import_count)`` ordered by import count."""
        async with self._sessions() as session:
            stmt = (
                select(col(Node.file_path), func.count())
                .where(col(Node.kind) == NodeKind.IMPORT)
                .group_by(col(Node.file_path))
                .order_by(func.count().desc())
                .limit(limit)
            )
            rows = (await session.exec(stmt)).all()
            return [(str(path), int(count)) for path, count in rows]

    async def list_nodes(self, root: str | None = None) -> list[Node]:
        """Return nodes, optionally scoped to ``root``, in stable order."""
        async with self._sessions() as session:
            stmt = select(Node).order_by(
                col(Node.file_path), col(Node.kind), col(Node.start_line)
            )
            if root is not None:
                stmt = stmt.where(col(Node.root) == root)
            return list((await session.exec(stmt)).all())

    async def list_edges(self, root: str | None = None) -> list[Edge]:
        """Return edges, optionally scoped to ``root``, in stable order."""
        async with self._sessions() as session:
            stmt = select(Edge).order_by(col(Edge.src_id), col(Edge.kind))
            if root is not None:
                stmt = stmt.where(col(Edge.root) == root)
            return list((await session.exec(stmt)).all())

    async def dispose(self) -> None:
        """Dispose the engine connection pool."""
        await self._engine.dispose()


def create_store(url: str) -> GraphStore:
    """Create a :class:`GraphStore` bound to ``url``."""
    return GraphStore(url)


def _enum_value(kind: NodeKind | EdgeKind | str) -> str:
    """Normalise a kind key to its plain string value."""
    if isinstance(kind, enum.Enum):
        return str(kind.value)
    text: str = str(kind)
    # ``str()`` of a str-enum member may render as "NodeKind.FILE";
    # reduce that to the trailing value.
    if "." in text and not text.startswith((".", "/")):
        candidate: str = text.rsplit(".", 1)[-1].lower()
        if candidate in ("file", "class", "function", "import", "contains", "imports"):
            return candidate
    return text


__all__ = ["EdgeKind", "GraphStore", "NodeKind", "create_store"]
