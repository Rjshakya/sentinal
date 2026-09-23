"""Linear code-graph pipeline: read -> build -> out.

- :func:`read`: discover + read source files (I/O).
- :func:`build_graph`: parse units into nodes/edges (pure).
- :func:`out`: persist + print (I/O).
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from codegraph.config import ResolvedDb
from codegraph.models import Edge, Node
from codegraph.parser.links import build_import_index
from codegraph.parser.rows import FileRows, build_python_file_rows
from codegraph.store import create_store
from codegraph.tree import GraphSnapshot, kind_label, load_snapshot, render_tree
from codegraph.walk import DiscoveredFile, adiscover_files, normalise_root

OutputMode = Literal["summary", "tree", "nodes", "calls"]
"""``out`` modes: summary line, hierarchy tree, node dump, call list."""


@dataclass(frozen=True, slots=True)
class FileInput:
    """One file's source text plus its identity (I/O edge output)."""

    rel_path: str
    language: str
    source_text: str


@dataclass(frozen=True, slots=True)
class ScannedSources:
    """One scan root plus its read source inputs."""

    root: str
    items: list[FileInput]


@dataclass(frozen=True, slots=True)
class BuiltGraph:
    """Merged pure build output for one root: nodes + edges, nothing else."""

    root: str
    files: int
    skipped: int
    nodes: tuple[Node, ...]
    edges: tuple[Edge, ...]


@dataclass(frozen=True, slots=True)
class IndexResult:
    """Outcome of one :func:`out` run."""

    root: str
    db_label: str
    files: int
    nodes: int
    edges: int
    skipped: int


async def _read_source(path: Path) -> str:
    """Read a source file off the event loop."""
    return await asyncio.to_thread(path.read_text, encoding="utf-8", errors="ignore")


async def read(target: Path) -> ScannedSources:
    """Discover + read every supported file under ``target``."""
    root_path: Path = (
        normalise_root(target) if target.is_dir() else normalise_root(target.parent)
    )
    root: str = root_path.as_posix()
    discovered: list[DiscoveredFile] = await adiscover_files(target, root_path)
    items: list[FileInput] = []
    for item in discovered:
        try:
            text: str = await _read_source(item.abs_path)
        except OSError:
            continue
        items.append(
            FileInput(rel_path=item.rel_path, language=item.language, source_text=text)
        )
    return ScannedSources(root=root, items=items)


def parse_file_input(
    root: str, item: FileInput, import_index: Mapping[str, str] | None = None
) -> FileRows | None:
    """Parse one file into rows. Returns None when the file is skipped.

    Pure given ``item``. Only Python is wired for now (blank source or
    any other language -> skip, counted by the caller).
    """
    if not item.source_text.strip():
        return None
    if item.language != "python":
        return None
    return build_python_file_rows(
        root, item.rel_path, item.source_text, import_index or {}
    )


def build_graph(root: str, items: list[FileInput]) -> BuiltGraph:
    """Run the full pure build: index imports, parse every file, merge."""
    import_index: dict[str, str] = build_import_index(i.rel_path for i in items)
    rows: list[FileRows] = []
    skipped: int = 0
    for item in items:
        file_rows: FileRows | None = parse_file_input(root, item, import_index)
        if file_rows is None:
            skipped += 1
            continue
        rows.append(file_rows)

    return BuiltGraph(
        root=root,
        files=len(rows),
        skipped=skipped,
        nodes=tuple(n for unit in rows for n in unit.nodes),
        edges=tuple(e for unit in rows for e in unit.edges),
    )


async def _snapshot_for(
    db: ResolvedDb, root: str, graph: BuiltGraph | None
) -> GraphSnapshot:
    """Return the snapshot to render: in-memory build or stored rows."""
    if graph is not None:
        return GraphSnapshot(root=root, nodes=graph.nodes, edges=graph.edges)
    store = create_store(db.url)
    try:
        await store.create_all()
        return await load_snapshot(store, root)
    finally:
        await store.dispose()


def _span_of(node: Node) -> str:
    """Format a node's line range as ``(Lstart-Lend)``."""
    return f"(L{node.start_line}-L{node.end_line})"


async def print_tree(db: ResolvedDb, root: str, graph: BuiltGraph | None = None) -> int:
    """Print the hierarchy tree of one indexed ``root``."""
    snapshot: GraphSnapshot = await _snapshot_for(db, root, graph)
    if not snapshot.nodes:
        print(f"no nodes for root {root}")
        return 0
    try:
        print(render_tree(snapshot))
    except UnicodeEncodeError:
        print(render_tree(snapshot, use_unicode=False))
    return 0


async def print_nodes(
    db: ResolvedDb, root: str, graph: BuiltGraph | None = None
) -> int:
    """Print every collected node of ``root`` for manual analysis."""
    snapshot = await _snapshot_for(db, root, graph)
    if not snapshot.nodes:
        print(f"no nodes for root {root}")
        return 0
    by_id: dict[str, Node] = {n.id: n for n in snapshot.nodes}
    by_file_name: dict[tuple[str, str], Node] = {}
    for n in sorted(snapshot.nodes, key=lambda x: (x.file_path, x.start_line)):
        if kind_label(n.kind) in ("class", "function", "method"):
            by_file_name.setdefault((n.file_path, n.name), n)
    children: dict[str, list[str]] = {}
    calls: dict[str, list[Edge]] = {}
    for edge in snapshot.edges:
        label: str = kind_label(edge.kind)
        if label in ("contains", "imports"):
            children.setdefault(edge.src_id, []).append(edge.dst_id)
        elif label == "calls":
            calls.setdefault(edge.src_id, []).append(edge)

    def names(node_ids: list[str]) -> str:
        resolved: list[str] = sorted({by_id[i].name for i in node_ids if i in by_id})
        return f"[{', '.join(resolved)}]"

    def _callee_order_key(call: Edge) -> tuple[int, int, str]:
        """Implementation order: call-site line, then callee name."""
        if call.site_line is not None:
            return (0, call.site_line, "")
        return (1, 1 << 30, call.dst_id)

    def callee_names(call_edges: list[Edge]) -> str:
        """Names for calls dsts in implementation order; assumed refs resolve via (file, name)."""
        resolved: list[tuple[tuple[int, int, str], str]] = []
        for call in call_edges:
            dst_id: str = call.dst_id
            node: Node | None = by_id.get(dst_id)
            if node is not None:
                resolved.append((_callee_order_key(call), node.name))
                continue
            parts: list[str] = dst_id.split(":")
            if len(parts) == 2:
                hit: Node | None = by_file_name.get((parts[0], parts[1]))
                resolved.append(
                    (
                        _callee_order_key(call),
                        parts[1] if hit is not None else f"{parts[1]}?",
                    )
                )
            else:
                resolved.append((_callee_order_key(call), f"{dst_id}?"))
        resolved.sort(key=lambda item: item[0])
        seen: set[str] = set()
        ordered: list[str] = []
        for _, name in resolved:
            if name not in seen:
                seen.add(name)
                ordered.append(name)
        return f"[{', '.join(ordered)}]"

    print(f"root: {root}  (nodes={len(snapshot.nodes)} edges={len(snapshot.edges)})")
    ordered_nodes: list[Node] = sorted(
        snapshot.nodes, key=lambda n: (n.file_path, n.start_line, n.name)
    )
    for node in ordered_nodes:
        parent: str = by_id[node.parent_id].name if node.parent_id in by_id else "None"
        print(
            f"node {kind_label(node.kind):8} {node.name} "
            f"[{node.language}] {_span_of(node)} "
            f"file={node.file_path} parent={parent} "
            f"children={names(children.get(node.id, []))} "
            f"callees={callee_names(calls.get(node.id, []))}"
        )
    return 0


async def print_calls(
    db: ResolvedDb, root: str, graph: BuiltGraph | None = None
) -> int:
    """Print every ``calls`` edge of ``root`` as ``caller -> callee``.

    Assumed refs (``base:name``) resolve via ``(file, name)``; a miss
    renders ``name?`` — the broken-import signal.
    """
    snapshot = await _snapshot_for(db, root, graph)
    by_id: dict[str, Node] = {n.id: n for n in snapshot.nodes}
    by_file_name: dict[tuple[str, str], Node] = {}
    for n in sorted(snapshot.nodes, key=lambda x: (x.file_path, x.start_line)):
        if kind_label(n.kind) in ("class", "function", "method"):
            by_file_name.setdefault((n.file_path, n.name), n)
    pairs: list[tuple[str, str, str, int]] = []
    for edge in snapshot.edges:
        if kind_label(edge.kind) != "calls":
            continue
        src: Node | None = by_id.get(edge.src_id)
        if src is None:
            continue
        site_line: int = edge.site_line if edge.site_line is not None else 1 << 30
        dst: Node | None = by_id.get(edge.dst_id)
        if dst is not None:
            pairs.append((src.name, dst.name, src.file_path, site_line))
            continue
        parts: list[str] = edge.dst_id.split(":")
        if len(parts) == 2 and by_file_name.get((parts[0], parts[1])) is not None:
            pairs.append((src.name, parts[1], src.file_path, site_line))
        else:
            name: str = parts[1] if len(parts) == 2 else edge.dst_id
            pairs.append((src.name, f"{name}?", src.file_path, site_line))
    if not pairs:
        print(f"no calls for root {root}")
        return 0
    pairs.sort(key=lambda item: (item[2], item[3], item[0], item[1]))
    print(f"root: {root}  (calls={len(pairs)})")
    for caller, callee, file_path, _ in pairs:
        print(f"calls {caller} -> {callee}  file={file_path}")
    return 0


async def out(
    db: ResolvedDb,
    root: str,
    graph: BuiltGraph,
    *,
    overwrite: bool,
    output: OutputMode = "summary",
    quiet: bool = True,
    persist: bool = True,
) -> IndexResult:
    """Persist ``graph`` (flushing first when ``overwrite``), then print."""
    if persist:
        if overwrite:
            store = create_store(db.url)
            try:
                await store.create_all()
                await store.clear_all()
            finally:
                await store.dispose()
        if graph.nodes or graph.edges:
            store = create_store(db.url)
            try:
                await store.create_all()
                await store.add_all(list(graph.nodes), list(graph.edges))
            finally:
                await store.dispose()

    if not quiet:
        verb: str = "indexed" if persist else "scanned"
        print(
            f"{verb} {graph.files} files, {len(graph.nodes)} nodes, "
            f"{len(graph.edges)} edges -> {db.label} [{root}]"
            + (f" ({graph.skipped} skipped)" if graph.skipped else "")
        )
    if output == "tree":
        await print_tree(db, root, graph if not persist else None)
    elif output == "nodes":
        await print_nodes(db, root, graph if not persist else None)
    elif output == "calls":
        await print_calls(db, root, graph if not persist else None)
    return IndexResult(
        root=root,
        db_label=db.label,
        files=graph.files,
        nodes=len(graph.nodes),
        edges=len(graph.edges),
        skipped=graph.skipped,
    )


__all__ = [
    "BuiltGraph",
    "FileInput",
    "IndexResult",
    "OutputMode",
    "ScannedSources",
    "build_graph",
    "out",
    "parse_file_input",
    "print_calls",
    "print_nodes",
    "print_tree",
    "read",
]
