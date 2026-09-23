"""Ladybug persistence for the code graph.

Embedded property-graph backend. Schema (created once via
:meth:`LadybugStore.create_all`):

- ``CodeNode`` — one row per structural node (``id`` primary key).
  Assumed cross-file callee refs (``base:name``) with no matching def
  are stored as stub rows (``is_placeholder=true``); the stub's
  presence is the broken-import signal.
- ``Contains`` / ``Imports`` / ``Calls`` — rel tables between
  ``CodeNode`` rows (``site_line`` on ``Calls``, ``target_module`` on
  ``Imports``).

Bulk ingest uses single-call ``execute`` + ``UNWIND $batch`` (no
dataframe dependency). Callers never touch the connection directly
beyond :func:`create_store`.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import ladybug as lb

from codegraph.models import Edge, EdgeKind, Node, NodeKind

_DEF_KINDS: frozenset[str] = frozenset({"class", "function", "method"})


async def _fetch(
    conn: lb.AsyncConnection, query: str, params: dict[str, Any] | None = None
) -> list[tuple[Any, ...]]:
    """Run ``query`` and return rows as plain tuples.

    Ladybug rows index positionally at runtime, but the shipped stubs
    type ``QueryResult.__getitem__`` as str-keyed only — so normalise
    through ``tuple()`` once, here, and keep the rest of the module
    strictly typed.
    """
    result: Any = await conn.execute(query, params or {})
    return [tuple(row) for row in result]


class LadybugStore:
    """Owns one Ladybug database + async connection."""

    def __init__(self, path: str) -> None:
        self._path: str = path
        self._db: lb.Database = lb.Database(path)
        self._conn: lb.AsyncConnection = lb.AsyncConnection(self._db)

    async def create_all(self) -> None:
        """Create node/rel tables when they do not exist yet."""
        await self._conn.execute(
            "CREATE NODE TABLE IF NOT EXISTS CodeNode("
            "id STRING PRIMARY KEY, root STRING, file_path STRING, "
            "kind STRING, name STRING, language STRING, "
            "start_line INT64, end_line INT64, "
            "parent_id STRING, is_placeholder BOOLEAN DEFAULT false)"
        )
        await self._conn.execute(
            "CREATE REL TABLE IF NOT EXISTS Contains(FROM CodeNode TO CodeNode)"
        )
        await self._conn.execute(
            "CREATE REL TABLE IF NOT EXISTS Imports("
            "FROM CodeNode TO CodeNode, target_module STRING)"
        )
        await self._conn.execute(
            "CREATE REL TABLE IF NOT EXISTS Calls("
            "FROM CodeNode TO CodeNode, site_line INT64)"
        )

    async def clear_all(self) -> None:
        """Delete every node/edge row in the database (full flush)."""
        await self._conn.execute("MATCH (n:CodeNode) DETACH DELETE n")

    async def clear_root(self, root: str) -> None:
        """Delete every node/edge previously indexed under ``root``."""
        await self._conn.execute(
            "MATCH (n:CodeNode) WHERE n.root = $root DETACH DELETE n",
            {"root": root},
        )

    async def add_all(self, nodes: Sequence[Node], edges: Sequence[Edge]) -> None:
        """Bulk-insert one batch of nodes plus their edges.

        Dangling ``CALLS`` targets (``base:name`` with no matching def
        in the batch) become placeholder stubs so every rel has both
        endpoints.
        """
        node_rows: list[dict[str, Any]] = [
            {
                "id": n.id,
                "root": n.root,
                "file_path": n.file_path,
                "kind": n.kind.value,
                "name": n.name,
                "language": n.language,
                "start_line": n.start_line,
                "end_line": n.end_line,
                "parent_id": n.parent_id,
                "is_placeholder": n.is_placeholder,
            }
            for n in nodes
        ]
        def_id_by_file_name: dict[tuple[str, str], str] = {}
        for n in nodes:
            if n.kind.value in _DEF_KINDS and not n.is_placeholder:
                def_id_by_file_name.setdefault((n.file_path, n.name), n.id)
        stubs: dict[str, dict[str, Any]] = {}
        contains_rows: list[dict[str, Any]] = []
        imports_rows: list[dict[str, Any]] = []
        calls_rows: list[dict[str, Any]] = []
        for e in edges:
            if e.kind == EdgeKind.CONTAINS:
                contains_rows.append({"src": e.src_id, "dst": e.dst_id})
            elif e.kind == EdgeKind.IMPORTS:
                imports_rows.append(
                    {"src": e.src_id, "dst": e.dst_id, "mod": e.target_module}
                )
            else:
                # Assumed refs are ``base:name`` — never a stored id.
                # Rewrite resolvable ones to the real def id; stub the rest.
                dst_id: str = e.dst_id
                parts: list[str] = dst_id.split(":")
                if len(parts) == 2:
                    real_id: str | None = def_id_by_file_name.get((parts[0], parts[1]))
                    if real_id is not None:
                        dst_id = real_id
                    else:
                        stubs.setdefault(
                            dst_id,
                            {
                                "id": dst_id,
                                "root": e.root,
                                "file_path": parts[0],
                                "kind": NodeKind.FUNCTION.value,
                                "name": parts[1],
                                "language": "",
                                "start_line": 1,
                                "end_line": 1,
                                "parent_id": None,
                                "is_placeholder": True,
                            },
                        )
                calls_rows.append({"src": e.src_id, "dst": dst_id, "site": e.site_line})
        node_rows.extend(stubs.values())
        if node_rows:
            await self._conn.execute(
                "UNWIND $batch AS row CREATE (n:CodeNode {"
                "id: row.id, root: row.root, file_path: row.file_path, "
                "kind: row.kind, name: row.name, language: row.language, "
                "start_line: row.start_line, end_line: row.end_line, "
                "parent_id: row.parent_id, is_placeholder: row.is_placeholder})",
                {"batch": node_rows},
            )
        if contains_rows:
            await self._conn.execute(
                "UNWIND $batch AS row "
                "MATCH (a:CodeNode {id: row.src}), (b:CodeNode {id: row.dst}) "
                "CREATE (a)-[:Contains]->(b)",
                {"batch": contains_rows},
            )
        if imports_rows:
            await self._conn.execute(
                "UNWIND $batch AS row "
                "MATCH (a:CodeNode {id: row.src}), (b:CodeNode {id: row.dst}) "
                "CREATE (a)-[:Imports {target_module: row.mod}]->(b)",
                {"batch": imports_rows},
            )
        if calls_rows:
            await self._conn.execute(
                "UNWIND $batch AS row "
                "MATCH (a:CodeNode {id: row.src}), (b:CodeNode {id: row.dst}) "
                "CREATE (a)-[:Calls {site_line: row.site}]->(b)",
                {"batch": calls_rows},
            )

    async def count_by_node_kind(self, root: str | None = None) -> dict[str, int]:
        """Return row counts grouped by node kind (keys are kind values)."""
        query: str = "MATCH (n:CodeNode)"
        params: dict[str, Any] = {}
        if root is not None:
            query += " WHERE n.root = $root"
            params["root"] = root
        query += " RETURN n.kind AS k, COUNT(*) AS c"
        return {str(k): int(c) for k, c in await _fetch(self._conn, query, params)}

    async def count_by_edge_kind(self, root: str | None = None) -> dict[str, int]:
        """Return row counts grouped by edge kind (keys are kind values)."""
        out: dict[str, int] = {}
        for label in ("Contains", "Imports", "Calls"):
            query: str = f"MATCH (a:CodeNode)-[e:{label}]->(:CodeNode)"
            params: dict[str, Any] = {}
            if root is not None:
                query += " WHERE a.root = $root"
                params["root"] = root
            rows: list[tuple[Any, ...]] = await _fetch(
                self._conn, query + " RETURN COUNT(*)", params
            )
            out[label.lower()] = int(rows[0][0])
        return out

    async def count_by_language(self, root: str | None = None) -> dict[str, int]:
        """Return file-node counts grouped by language."""
        query: str = "MATCH (n:CodeNode) WHERE n.kind = 'file'"
        params: dict[str, Any] = {}
        if root is not None:
            query += " AND n.root = $root"
            params["root"] = root
        query += " RETURN n.language AS l, COUNT(*) AS c"
        return {str(l): int(c) for l, c in await _fetch(self._conn, query, params)}

    async def total_counts(self, root: str | None = None) -> tuple[int, int, int]:
        """Return ``(files, nodes, edges)`` totals."""
        params: dict[str, Any] = {"root": root} if root is not None else {}
        root_and: str = " AND n.root = $root" if root is not None else ""
        root_where_a: str = " WHERE a.root = $root" if root is not None else ""
        files_rows: list[tuple[Any, ...]] = await _fetch(
            self._conn,
            "MATCH (n:CodeNode) WHERE n.kind = 'file'" + root_and + " RETURN COUNT(*)",
            params,
        )
        nodes_rows: list[tuple[Any, ...]] = await _fetch(
            self._conn,
            "MATCH (n:CodeNode)"
            + (" WHERE n.root = $root" if root is not None else "")
            + " RETURN COUNT(*)",
            params,
        )
        edge_total: int = 0
        for label in ("Contains", "Imports", "Calls"):
            rel_rows: list[tuple[Any, ...]] = await _fetch(
                self._conn,
                f"MATCH (a:CodeNode)-[:{label}]->(:CodeNode)"
                + root_where_a
                + " RETURN COUNT(*)",
                params,
            )
            edge_total += int(rel_rows[0][0])
        return (int(files_rows[0][0]), int(nodes_rows[0][0]), edge_total)

    async def top_importers(self, limit: int = 10) -> list[tuple[str, int]]:
        """Return ``(file_path, import_count)`` ordered by import count."""
        rows: list[tuple[Any, ...]] = await _fetch(
            self._conn,
            "MATCH (a:CodeNode)-[:Imports]->(:CodeNode) "
            "RETURN a.file_path AS p, COUNT(*) AS c "
            "ORDER BY c DESC LIMIT $limit",
            {"limit": limit},
        )
        return [(str(path), int(count)) for path, count in rows]

    async def list_nodes(self, root: str | None = None) -> list[Node]:
        """Return nodes, optionally scoped to ``root``, in stable order."""
        query: str = (
            "MATCH (n:CodeNode)"
            + (" WHERE n.root = $root" if root is not None else "")
            + " RETURN n.id, n.root, n.file_path, n.kind, n.name, "
            "n.language, n.start_line, n.end_line, n.parent_id, n.is_placeholder "
            "ORDER BY n.file_path, n.kind, n.start_line"
        )
        params: dict[str, Any] = {"root": root} if root is not None else {}
        found: list[Node] = []
        for row in await _fetch(self._conn, query, params):
            found.append(
                Node(
                    id=str(row[0]),
                    root=str(row[1]),
                    file_path=str(row[2]),
                    kind=NodeKind(str(row[3])),
                    name=str(row[4]),
                    language=str(row[5]),
                    start_line=int(row[6]),
                    end_line=int(row[7]),
                    parent_id=str(row[8]) if row[8] is not None else None,
                    is_placeholder=bool(row[9]),
                )
            )
        return found

    async def list_edges(self, root: str | None = None) -> list[Edge]:
        """Return edges, optionally scoped to ``root``, in stable order."""
        params: dict[str, Any] = {"root": root} if root is not None else {}
        where: str = " WHERE a.root = $root" if root is not None else ""
        found: list[Edge] = []
        for row in await _fetch(
            self._conn,
            "MATCH (a:CodeNode)-[:Contains]->(b:CodeNode)"
            + where
            + " RETURN a.root, a.id, b.id",
            params,
        ):
            found.append(
                Edge(
                    id=f"{row[1]}::contains::{row[2]}",
                    root=str(row[0]),
                    src_id=str(row[1]),
                    dst_id=str(row[2]),
                    kind=EdgeKind.CONTAINS,
                )
            )
        for row in await _fetch(
            self._conn,
            "MATCH (a:CodeNode)-[e:Imports]->(b:CodeNode)"
            + where
            + " RETURN a.root, a.id, b.id, e.target_module",
            params,
        ):
            found.append(
                Edge(
                    id=f"{row[1]}::imports::{row[2]}",
                    root=str(row[0]),
                    src_id=str(row[1]),
                    dst_id=str(row[2]),
                    kind=EdgeKind.IMPORTS,
                    target_module=str(row[3]) if row[3] is not None else None,
                )
            )
        for row in await _fetch(
            self._conn,
            "MATCH (a:CodeNode)-[e:Calls]->(b:CodeNode)"
            + where
            + " RETURN a.root, a.id, b.id, e.site_line",
            params,
        ):
            found.append(
                Edge(
                    id=f"{row[1]}::calls::{row[2]}",
                    root=str(row[0]),
                    src_id=str(row[1]),
                    dst_id=str(row[2]),
                    kind=EdgeKind.CALLS,
                    site_line=int(row[3]) if row[3] is not None else None,
                )
            )
        found.sort(key=lambda e: (e.src_id, e.kind.value))
        return found

    async def dispose(self) -> None:
        """Release the connection (embedded DB needs no pool teardown)."""
        return None


def create_store(path: str) -> LadybugStore:
    """Create a :class:`LadybugStore` bound to ``path`` (or ``:memory:``)."""
    return LadybugStore(path)


__all__ = ["EdgeKind", "LadybugStore", "NodeKind", "create_store"]
