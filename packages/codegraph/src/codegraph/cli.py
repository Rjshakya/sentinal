"""Sentinel code graph CLI (fully async).

Usage:
    codegraph index <path> --db ./codegraph.db [--overwrite] [--quiet] [--output {summary,tree,nodes}]
    codegraph stats --db ./codegraph.db
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from codegraph.config import ResolvedDb, resolve_db
from codegraph.models import Edge, Node
from codegraph.parser import build_file_rows, parse_source_text, resolve_call_edges
from codegraph.parser import FileRows
from codegraph.parser.base import ParsedFile
from codegraph.store import create_store
from codegraph.tree import GraphSnapshot, kind_label, load_snapshot, render_tree
from codegraph.walk import DiscoveredFile, adiscover_files, normalise_root

BATCH_SIZE: int = 100
"""Rows are flushed to the database in batches of this size."""

OutputMode = Literal["summary", "tree", "nodes"]
"""``index`` output modes: one-line summary, hierarchy tree, node dump."""


@dataclass(frozen=True, slots=True)
class IndexResult:
    """Outcome of one ``index`` run."""

    root: str
    db_label: str
    files: int
    nodes: int
    edges: int
    skipped: int


async def _read_source(path: Path) -> str:
    """Read a source file off the event loop."""
    return await asyncio.to_thread(path.read_text, encoding="utf-8", errors="ignore")


async def _index_one(
    discovered: DiscoveredFile, root: str
) -> tuple[FileRows | None, bool]:
    """Parse one file and build its rows.

    Returns ``(rows, skipped)`` — ``skipped`` is True when the file
    could not be read or parsed and must be counted, not stored.
    ``calls`` edges are not included; they resolve globally in
    :func:`run_index` after every file has been built.
    """
    try:
        source_text: str = await _read_source(discovered.abs_path)
    except OSError:
        return (None, True)
    if not source_text.strip():
        return (None, True)
    # NOTE: parsing runs on the event-loop thread, never in a worker:
    # tree-sitter Parser/Tree/Node objects are not thread-safe, and the
    # module-level parser cache must only be touched from one thread.
    # Parse is CPU-bound but sub-millisecond per file, so this does not
    # stall the loop in practice. Only file I/O goes via to_thread.
    try:
        parsed: ParsedFile = parse_source_text(discovered.language, source_text)
    except ValueError:
        return (None, True)
    rows: FileRows = build_file_rows(
        root=root,
        rel_path=discovered.rel_path,
        language=discovered.language,
        parsed=parsed,
    )
    return (rows, False)


async def run_index(
    target: Path, db: ResolvedDb, overwrite: bool, quiet: bool,
    output: OutputMode = "summary",
) -> IndexResult:
    """Walk ``target``, parse every supported file, and persist the graph.

    With ``output="tree"``, the hierarchy tree of the indexed root is
    printed afterwards; with ``output="nodes"``, every collected node
    is printed instead. An explicit request always prints, even when
    ``quiet`` suppresses the summary line.
    """
    if target.is_dir():
        root_path: Path = normalise_root(target)
    else:
        root_path = normalise_root(target.parent)
    root: str = root_path.as_posix()

    discovered: list[DiscoveredFile] = await adiscover_files(target, root_path)
    store = create_store(db.url)
    files: int = 0
    run_nodes: int = 0
    run_edges: int = 0
    skipped: int = 0
    try:
        await store.create_all()
        if overwrite:
            await store.clear_root(root)

        batch_nodes: list[Node] = []
        batch_edges: list[Edge] = []
        file_rows: list[FileRows] = []
        for item in discovered:
            rows, was_skipped = await _index_one(item, root)
            if was_skipped or rows is None:
                skipped += 1
                continue
            files += 1
            file_rows.append(rows)
        # Second pass: call sites resolve against the global
        # (rel_path, name) map, so cross-file calls become edges.
        call_edges: list[Edge] = resolve_call_edges(file_rows, root)
        for rows in file_rows:
            run_nodes += len(rows.nodes)
            run_edges += len(rows.edges)
            batch_nodes.extend(rows.nodes)
            batch_edges.extend(rows.edges)
            if len(batch_nodes) >= BATCH_SIZE:
                await store.add_all(batch_nodes, batch_edges)
                batch_nodes = []
                batch_edges = []
        run_edges += len(call_edges)
        batch_edges.extend(call_edges)
        if batch_nodes or batch_edges:
            await store.add_all(batch_nodes, batch_edges)
    finally:
        await store.dispose()

    if not quiet:
        print(
            f"indexed {files} files, {run_nodes} nodes, "
            f"{run_edges} edges -> {db.label} [{root}]"
            + (f" ({skipped} skipped)" if skipped else "")
        )
    if output == "tree":
        await print_tree(db, root)
    elif output == "nodes":
        await print_nodes(db, root)
    return IndexResult(
        root=root,
        db_label=db.label,
        files=files,
        nodes=run_nodes,
        edges=run_edges,
        skipped=skipped,
    )


async def print_tree(db: ResolvedDb, root: str) -> int:
    """Print the hierarchy tree of one indexed ``root``.

    Reads the graph back from the database (so the output reflects
    stored node ↔ edge ↔ root relations) and prints it. Returns the
    process exit code.
    """
    store = create_store(db.url)
    try:
        await store.create_all()
        snapshot: GraphSnapshot = await load_snapshot(store, root)
    finally:
        await store.dispose()
    if not snapshot.nodes:
        print(f"no nodes for root {root}")
        return 0
    try:
        print(render_tree(snapshot))
    except UnicodeEncodeError:
        # Windows cp1252 console (and similar): retry with ASCII glyphs.
        print(render_tree(snapshot, use_unicode=False))
    return 0


async def print_nodes(db: ResolvedDb, root: str) -> int:
    """Print every collected node of ``root`` for manual analysis.

    One line per node: kind, name, file, language, line span, parent
    name, structural children names, and callee names. Returns the
    process exit code.
    """
    store = create_store(db.url)
    try:
        await store.create_all()
        snapshot = await load_snapshot(store, root)
    finally:
        await store.dispose()
    if not snapshot.nodes:
        print(f"no nodes for root {root}")
        return 0
    by_id: dict[str, Node] = {n.id: n for n in snapshot.nodes}
    children: dict[str, list[str]] = {}
    callees: dict[str, list[str]] = {}
    for edge in snapshot.edges:
        label: str = kind_label(edge.kind)
        if label in ("contains", "imports"):
            children.setdefault(edge.src_id, []).append(edge.dst_id)
        elif label == "calls":
            callees.setdefault(edge.src_id, []).append(edge.dst_id)

    def names(node_ids: list[str]) -> str:
        resolved: list[str] = sorted(
            {by_id[i].name for i in node_ids if i in by_id}
        )
        return f"[{', '.join(resolved)}]"

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
            f"callees={names(callees.get(node.id, []))}"
        )
    return 0


def _span_of(node: Node) -> str:
    """Format a node's line range as ``(Lstart-Lend)``."""
    return f"(L{node.start_line}-L{node.end_line})"


async def run_stats(db: ResolvedDb) -> int:
    """Print database statistics and return the process exit code."""
    store = create_store(db.url)
    try:
        await store.create_all()
        files, nodes, edges = await store.total_counts()
        by_kind = await store.count_by_node_kind()
        by_edge = await store.count_by_edge_kind()
        by_lang = await store.count_by_language()
        top = await store.top_importers()
    finally:
        await store.dispose()
    print(f"db: {db.label}")
    print(f"files: {files}  nodes: {nodes}  edges: {edges}")
    if by_kind:
        print("nodes by kind: " + ", ".join(f"{k}={v}" for k, v in sorted(by_kind.items())))
    if by_edge:
        print("edges by kind: " + ", ".join(f"{k}={v}" for k, v in sorted(by_edge.items())))
    if by_lang:
        print("files by language: " + ", ".join(f"{k}={v}" for k, v in sorted(by_lang.items())))
    if top:
        print("top importing files:")
        for path, count in top:
            print(f"  {count:4d}  {path}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser."""
    parser = argparse.ArgumentParser(
        prog="codegraph",
        description="Sentinel code graph CLI: tree-sitter nodes/edges into SQL",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    index_cmd = sub.add_parser("index", help="index a dir/file into the database")
    index_cmd.add_argument("path", help="directory or file to index")
    index_cmd.add_argument(
        "--db", default="./codegraph.db", help="SQLite path or SQLAlchemy URL"
    )
    index_cmd.add_argument(
        "--overwrite",
        action="store_true",
        help="delete previous rows for this root before indexing",
    )
    index_cmd.add_argument(
        "--quiet", action="store_true", help="suppress the summary line"
    )
    index_cmd.add_argument(
        "--output",
        choices=("summary", "tree", "nodes"),
        default="summary",
        help="index output: one-line summary (default), hierarchy tree, or node dump",
    )

    stats_cmd = sub.add_parser("stats", help="print database statistics")
    stats_cmd.add_argument(
        "--db", default="./codegraph.db", help="SQLite path or SQLAlchemy URL"
    )
    return parser


async def amain(argv: list[str] | None = None) -> int:
    """Async entry point (kept separate for testability)."""
    args = build_parser().parse_args(argv)
    try:
        db: ResolvedDb = resolve_db(str(args.db))
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if args.command == "stats":
        return await run_stats(db)
    if args.command == "index":
        target = Path(str(args.path)).expanduser()
        if not target.exists():
            print(f"error: path does not exist: {target}", file=sys.stderr)
            return 2
        target_resolved: Path = target.resolve()
        raw_output: str = str(args.output)
        output: OutputMode = (
            "tree" if raw_output == "tree" else "nodes" if raw_output == "nodes" else "summary"
        )
        await run_index(
            target_resolved,
            db,
            overwrite=bool(args.overwrite),
            quiet=bool(args.quiet),
            output=output,
        )
        return 0
    return 2


def main(argv: list[str] | None = None) -> int:
    """Sync wrapper: run the async CLI."""
    return asyncio.run(amain(argv))


if __name__ == "__main__":
    raise SystemExit(main())
