"""Linear code-graph pipeline: read -> build -> out.

- :func:`read`: discover + read source files (I/O).
- :func:`build_graph`: collect per-file rows then link calls (pure).
- :func:`out`: persist + print (I/O).

Languages: Python, TypeScript/JavaScript, Go. Anything else discovered
is counted as skipped.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from codegraph.config import ResolvedDb
from codegraph.models import Edge, Node
from codegraph.parser.lang_go import build_go_file_rows
from codegraph.parser.lang_typescript import build_ts_file_rows
from codegraph.parser.links import resolve_call_edges
from codegraph.parser.rows import FileRows, build_python_file_rows
from codegraph.graph_store import create_store
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


_LANGUAGE_TO_BUILDER: dict[
    str, Callable[[str, str, str, Mapping[str, str]], FileRows]
] = {
    "python": build_python_file_rows,
    "typescript": build_ts_file_rows,
    "javascript": build_ts_file_rows,
    "go": build_go_file_rows,
}
"""Per-language collect builders; unknown languages skip at :func:`parse_file_input`."""


def parse_file_input(
    root: str, item: FileInput, import_index: Mapping[str, str] | None = None
) -> FileRows | None:
    """Parse one file into rows. Returns None when the file is skipped.

    Pure given ``item``. Blank source or a non-Python language -> skip,
    counted by the caller. ``import_index`` is accepted for
    signature stability and ignored: the link phase resolves modules
    from the full collected file set.
    """

    if not item.source_text.strip():
        return None
    handler: Callable[[str, str, str, Mapping[str, str]], FileRows] | None = (
        _LANGUAGE_TO_BUILDER.get(item.language)
    )

    if handler is None:
        return None
    return handler(root, item.rel_path, item.source_text, import_index or {})


def build_graph(root: str, items: list[FileInput]) -> BuiltGraph:
    """Run the full pure build in two passes: collect, then link.

    Pass 1 parses every Python file into nodes + ``contains`` /
    ``imports`` edges plus buffered call sites (no ``calls`` edges).
    Pass 2 joins the buffered sites against the global definition
    registry + per-file import maps into ``calls`` edges with real
    node ids; unresolvable sites yield no edge.
    """
    rows: list[FileRows] = []
    skipped: int = 0
    for item in items:
        file_rows: FileRows | None = parse_file_input(root, item)
        if file_rows is None:
            skipped += 1
            continue
        rows.append(file_rows)
    call_edges: list[Edge] = resolve_call_edges(rows, root)

    return BuiltGraph(
        root=root,
        files=len(rows),
        skipped=skipped,
        nodes=tuple(n for unit in rows for n in unit.nodes),
        edges=tuple(e for unit in rows for e in unit.edges) + tuple(call_edges),
    )


PrintableGraph = BuiltGraph | GraphSnapshot
"""Anything the printers can render: a fresh build or a stored snapshot."""


async def _snapshot_for(
    db: ResolvedDb, root: str, graph: PrintableGraph | None
) -> GraphSnapshot:
    """Return the snapshot to render: in-memory build or stored rows."""
    if graph is not None:
        return GraphSnapshot(root=root, nodes=graph.nodes, edges=graph.edges)
    store = create_store(db.path)
    try:
        await store.create_all()
        return await load_snapshot(store, root)
    finally:
        await store.dispose()


def _span_of(node: Node) -> str:
    """Format a node's line range as ``(Lstart-Lend)``."""
    return f"(L{node.start_line}-L{node.end_line})"


async def print_tree(
    db: ResolvedDb, root: str, graph: PrintableGraph | None = None
) -> int:
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
    db: ResolvedDb, root: str, graph: PrintableGraph | None = None
) -> int:
    """Print every collected node of ``root`` for manual analysis."""
    snapshot = await _snapshot_for(db, root, graph)
    if not snapshot.nodes:
        print(f"no nodes for root {root}")
        return 0
    by_id: dict[str, Node] = {n.id: n for n in snapshot.nodes}
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
        """Names for calls dsts in implementation order (dsts are real ids)."""
        resolved: list[tuple[tuple[int, int, str], str]] = []
        for call in call_edges:
            dst_id: str = call.dst_id
            node: Node | None = by_id.get(dst_id)
            if node is not None:
                resolved.append(
                    (
                        _callee_order_key(call),
                        f"{node.name}?" if node.is_placeholder else node.name,
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
    db: ResolvedDb, root: str, graph: PrintableGraph | None = None
) -> int:
    """Print every ``calls`` edge of ``root`` as ``caller -> callee``.

    Dsts are real node ids; a dst missing from the snapshot renders
    with a ``?`` suffix (defensive — the build never emits dangling
    edges since unresolved sites are dropped).
    """
    snapshot = await _snapshot_for(db, root, graph)
    by_id: dict[str, Node] = {n.id: n for n in snapshot.nodes}
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
            callee: str = f"{dst.name}?" if dst.is_placeholder else dst.name
        else:
            callee = f"{edge.dst_id}?"
        pairs.append((src.name, callee, src.file_path, site_line))
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
    """Persist ``graph`` (flushing first when ``overwrite``), then print.

    One store for the whole call, so ``:memory:`` databases stay alive
    from persist through the snapshot reads below.
    """
    stored: GraphSnapshot | None = None
    if persist:
        if not db.is_memory:
            # The default DB lives under ~/.codegraph/, which may not
            # exist on first run. Read paths never create directories.
            Path(db.path).parent.mkdir(parents=True, exist_ok=True)
        store = create_store(db.path)
        try:
            await store.create_all()
            if overwrite:
                await store.clear_all()
            if graph.nodes or graph.edges:
                await store.add_all(list(graph.nodes), list(graph.edges))
            if output in ("tree", "nodes", "calls"):
                stored = await load_snapshot(store, root)
        finally:
            await store.dispose()

    if not quiet:
        verb: str = "indexed" if persist else "scanned"
        print(
            f"{verb} {graph.files} files, {len(graph.nodes)} nodes, "
            f"{len(graph.edges)} edges -> {db.label} [{root}]"
            + (f" ({graph.skipped} skipped)" if graph.skipped else "")
        )
    rendered: PrintableGraph | None = stored if persist else graph
    if output == "tree":
        await print_tree(db, root, rendered)
    elif output == "nodes":
        await print_nodes(db, root, rendered)
    elif output == "calls":
        await print_calls(db, root, rendered)
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
    "PrintableGraph",
    "ScannedSources",
    "build_graph",
    "out",
    "parse_file_input",
    "print_calls",
    "print_nodes",
    "print_tree",
    "read",
]
