"""Sentinel code graph CLI (fully async, I/O at the edge).

Flow: ``amain`` parses args, then ``pipeline.read -> pipeline.build_graph
-> pipeline.out`` for indexing, or the read-only ``run_query`` /
``run_stats`` for inspection. Tree-sitter parsing runs on the
event-loop thread (``Parser`` / ``Tree`` / ``Node`` are not
thread-safe); only file I/O goes through ``to_thread``.

Usage:
    codegraph index <path> [--db PATH] [--overwrite] [--quiet]
        [--output {summary,tree,nodes,calls}] [--persist | --no-persist]
    codegraph stats [--db PATH]
    codegraph query [--db PATH] [--root ROOT] [--json] <verb> ...

``--db`` defaults to ``~/.codegraph/graph.lbdb`` (see
:mod:`codegraph.config`). The ``query`` verbs are built for agents:
start from ``files`` / ``search`` to discover node ids, then drill
with ``node`` / ``callees`` / ``callers`` / ``children`` / ``imports``.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

from codegraph.config import DEFAULT_DB, ResolvedDb, resolve_db
from codegraph.graph_store import LadybugStore, create_store
from codegraph.models import Node
from codegraph.pipeline import OutputMode, build_graph, out, read
from codegraph.query import (
    DEFAULT_SEARCH_LIMIT,
    envelope,
    exact_matches,
    render_human,
    search_nodes,
    to_item,
)


async def run_stats(db: ResolvedDb) -> int:
    """Print database statistics and return the process exit code."""
    store = create_store(db.path)
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
        print(
            "nodes by kind: "
            + ", ".join(f"{k}={v}" for k, v in sorted(by_kind.items()))
        )
    if by_edge:
        print(
            "edges by kind: "
            + ", ".join(f"{k}={v}" for k, v in sorted(by_edge.items()))
        )
    if by_lang:
        print(
            "files by language: "
            + ", ".join(f"{k}={v}" for k, v in sorted(by_lang.items()))
        )
    if top:
        print("top importing files:")
        for path, count in top:
            print(f"  {count:4d}  {path}")
    return 0


_QUERY_VERBS: tuple[str, ...] = (
    "overview",
    "files",
    "search",
    "node",
    "callees",
    "callers",
    "children",
    "imports",
)
"""Read-only exploration verbs (see :mod:`codegraph.query`)."""


def _add_db_arg(cmd: argparse.ArgumentParser) -> None:
    """Attach the shared ``--db`` flag (known-location default)."""
    cmd.add_argument(
        "--db",
        default=DEFAULT_DB,
        help=f"Ladybug database path or :memory: (default: {DEFAULT_DB})",
    )


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser."""
    parser = argparse.ArgumentParser(
        prog="codegraph",
        description="Sentinel code graph CLI: tree-sitter nodes/edges into SQL",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    index_cmd = sub.add_parser("index", help="index a dir/file into the database")
    index_cmd.add_argument("path", help="directory or file to index")
    _add_db_arg(index_cmd)
    index_cmd.add_argument(
        "--overwrite",
        action="store_true",
        help="flush all rows from the database before indexing",
    )
    index_cmd.add_argument(
        "--quiet", action="store_true", help="suppress the summary line"
    )
    index_cmd.add_argument(
        "--output",
        choices=("summary", "tree", "nodes", "calls"),
        default="summary",
        help="index output: summary (default), hierarchy tree, node dump, or call list",
    )
    index_cmd.add_argument(
        "--persist",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="persist rows to --db (use --no-persist for dry-run print only)",
    )

    stats_cmd = sub.add_parser("stats", help="print database statistics")
    _add_db_arg(stats_cmd)

    query_cmd = sub.add_parser(
        "query", help="explore the indexed graph (read-only, agent-friendly)"
    )
    _add_db_arg(query_cmd)
    query_cmd.add_argument(
        "--root",
        default=None,
        help="narrow to one indexed root (default: all roots)",
    )
    query_cmd.add_argument(
        "--json",
        action="store_true",
        help="emit the stable chaining envelope as JSON",
    )
    qsub = query_cmd.add_subparsers(dest="query_verb", required=True)
    qsub.add_parser("overview", help="index counts by kind and language")
    qsub.add_parser("files", help="indexed files (file ids are plain rel paths)")
    search_cmd = qsub.add_parser(
        "search", help="substring-match def names -> rows with ids"
    )
    search_cmd.add_argument("--name", required=True, help="name fragment to match")
    search_cmd.add_argument(
        "--kind",
        default=None,
        help="narrow to one node kind (class|function|method|interface|type)",
    )
    search_cmd.add_argument("--file", default=None, help="narrow to one rel path")
    search_cmd.add_argument(
        "--limit",
        type=int,
        default=DEFAULT_SEARCH_LIMIT,
        help=f"max hits (default: {DEFAULT_SEARCH_LIMIT})",
    )
    for verb in ("node", "callees", "callers", "children"):
        verb_cmd = qsub.add_parser(verb, help=f"{verb} for one node")
        verb_cmd.add_argument("--id", default=None, help="exact node id")
        verb_cmd.add_argument("--name", default=None, help="exact def name")
        verb_cmd.add_argument("--file", default=None, help="narrow --name to one file")
    imports_cmd = qsub.add_parser("imports", help="one file's imports")
    imports_cmd.add_argument("--file", default=None, help="file rel path")
    imports_cmd.add_argument("--id", default=None, help="exact file node id")
    return parser


def _missing_db_message(db: ResolvedDb) -> str:
    """Friendly error when a read targets a database that was never indexed."""
    return f"error: no database at {db.label}; run `codegraph index` first"


async def run_query(
    db: ResolvedDb,
    *,
    root_filter: str | None,
    verb: str,
    node_id: str | None,
    name: str | None,
    file: str | None,
    kind: str | None,
    limit: int,
    as_json: bool,
) -> int:
    """Run one read-only exploration verb against ``db``.

    Returns 0 on success (even with zero hits — ``count`` says so),
    1 on resolution errors (unknown id, no/ambiguous name, bad limit).
    Never writes rows.
    """
    root_label: str = root_filter if root_filter is not None else "all"
    store = create_store(db.path)
    try:
        await store.create_all()
        if verb == "overview":
            return await _run_overview(store, db, root_filter, root_label, as_json)
        if verb == "files":
            items: list[dict[str, Any]] = [
                to_item(n) for n in await store.list_files(root_filter)
            ]
            return _emit(db, root_label, verb, items, False, as_json)
        if verb == "search":
            if limit <= 0:
                print("error: --limit must be a positive integer", file=sys.stderr)
                return 1
            nodes: list[Node] = await store.list_nodes(root_filter)
            hits, truncated = search_nodes(
                nodes, name or "", kind=kind, file_path=file, limit=limit
            )
            return _emit(
                db, root_label, verb, [to_item(n) for n in hits], truncated, as_json
            )
        if verb == "imports":
            return await _run_imports(
                store, db, root_filter, root_label, node_id, file, as_json
            )
        return await _run_drill(
            store, db, root_filter, root_label, verb, node_id, name, file, as_json
        )
    finally:
        await store.dispose()


async def _run_overview(
    store: LadybugStore, db: ResolvedDb, root_filter: str | None, root_label: str, as_json: bool
) -> int:
    """Emit index counts (by kind, edge, language)."""
    files, nodes, edges = await store.total_counts(root_filter)
    by_kind = await store.count_by_node_kind(root_filter)
    by_edge = await store.count_by_edge_kind(root_filter)
    by_lang = await store.count_by_language(root_filter)
    if as_json:
        print(
            json.dumps(
                {
                    "root": root_label,
                    "verb": "overview",
                    "files": files,
                    "nodes": nodes,
                    "edges": edges,
                    "by_kind": by_kind,
                    "by_edge": by_edge,
                    "by_language": by_lang,
                },
                indent=2,
            )
        )
        return 0
    print(f"db: {db.label}")
    print(f"files: {files}  nodes: {nodes}  edges: {edges}")
    if by_kind:
        print(
            "nodes by kind: "
            + ", ".join(f"{k}={v}" for k, v in sorted(by_kind.items()))
        )
    if by_edge:
        print(
            "edges by kind: "
            + ", ".join(f"{k}={v}" for k, v in sorted(by_edge.items()))
        )
    if by_lang:
        print(
            "files by language: "
            + ", ".join(f"{k}={v}" for k, v in sorted(by_lang.items()))
        )
    return 0


def _emit(
    db: ResolvedDb,
    root_label: str,
    verb: str,
    items: list[dict[str, Any]],
    truncated: bool,
    as_json: bool,
) -> int:
    """Print one row-verb result as JSON envelope or human lines."""
    if as_json:
        payload: dict[str, Any] = envelope(root_label, verb, items)
        payload["truncated"] = truncated
        print(json.dumps(payload, indent=2))
    else:
        print(render_human(root_label, verb, items))
        if truncated:
            print("(truncated: narrow with --kind/--file/--limit)")
    return 0


async def _resolve_drill_target(
    store: LadybugStore,
    root_filter: str | None,
    node_id: str | None,
    name: str | None,
    file: str | None,
) -> Node | int:
    """Resolve ``--id`` / ``--name`` sugar to a node, or an exit code.

    Returns the :class:`Node` on success, else 1 after printing the
    error (unknown id, missing name, or ambiguity with hit counts).
    """
    if node_id is not None:
        node: Node | None = await store.get_node(node_id, root_filter)
        if node is None:
            print(f"error: no node with id {node_id!r}", file=sys.stderr)
            return 1
        return node
    if name is None:
        print("error: one of --id or --name is required", file=sys.stderr)
        return 1
    matches: list[Node] = exact_matches(
        await store.list_nodes(root_filter), name, file
    )
    if not matches:
        scope: str = f" in file {file!r}" if file else ""
        print(f"error: no node named {name!r}{scope}", file=sys.stderr)
        return 1
    if len(matches) > 1:
        print(f"error: ambiguous name {name!r} ({len(matches)} hits):", file=sys.stderr)
        for hit in matches:
            print(
                f"  {hit.id}  [{hit.kind.value}] file={hit.file_path}",
                file=sys.stderr,
            )
        print("narrow with --file or use --id", file=sys.stderr)
        return 1
    return matches[0]


async def _run_drill(
    store: LadybugStore,
    db: ResolvedDb,
    root_filter: str | None,
    root_label: str,
    verb: str,
    node_id: str | None,
    name: str | None,
    file: str | None,
    as_json: bool,
) -> int:
    """Run ``node`` / ``callees`` / ``callers`` / ``children``."""
    target: Node | int = await _resolve_drill_target(
        store, root_filter, node_id, name, file
    )
    if isinstance(target, int):
        return target
    items: list[dict[str, Any]] = []
    if verb == "node":
        items = [to_item(target)]
    elif verb == "callees":
        items = [
            {**to_item(node), "site_line": site}
            for node, site in await store.callees(target.id, root_filter)
        ]
    elif verb == "callers":
        items = [
            {**to_item(node), "site_line": site}
            for node, site in await store.callers(target.id, root_filter)
        ]
    else:  # children
        items = [to_item(node) for node in await store.children(target.id, root_filter)]
    return _emit(db, root_label, verb, items, False, as_json)


async def _run_imports(
    store: LadybugStore,
    db: ResolvedDb,
    root_filter: str | None,
    root_label: str,
    node_id: str | None,
    file: str | None,
    as_json: bool,
) -> int:
    """Run ``imports`` for one file (by rel path or file node id)."""
    file_rel: str | None = file
    if node_id is not None:
        node: Node | None = await store.get_node(node_id, root_filter)
        if node is None:
            print(f"error: no node with id {node_id!r}", file=sys.stderr)
            return 1
        if str(node.kind.value) != "file":
            print(
                f"error: node {node_id!r} is a {node.kind.value}, not a file "
                "(pass a file rel path via --file)",
                file=sys.stderr,
            )
            return 1
        file_rel = node.file_path
    if file_rel is None:
        print("error: one of --file or --id is required", file=sys.stderr)
        return 1
    items: list[dict[str, Any]] = [
        {**to_item(node), "target_module": module}
        for node, module in await store.file_imports(file_rel, root_filter)
    ]
    return _emit(db, root_label, "imports", items, False, as_json)


async def amain(argv: list[str] | None = None) -> int:
    """Async entry point (kept separate for testability)."""
    args = build_parser().parse_args(argv)
    try:
        db: ResolvedDb = resolve_db(str(args.db))
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if args.command == "stats":
        if not db.is_memory and not Path(db.path).exists():
            print(_missing_db_message(db), file=sys.stderr)
            return 1
        return await run_stats(db)
    if args.command == "query":
        if not db.is_memory and not Path(db.path).exists():
            print(_missing_db_message(db), file=sys.stderr)
            return 1
        return await run_query(
            db,
            root_filter=args.root,
            verb=str(args.query_verb),
            node_id=getattr(args, "id", None),
            name=getattr(args, "name", None),
            file=getattr(args, "file", None),
            kind=getattr(args, "kind", None),
            limit=int(getattr(args, "limit", DEFAULT_SEARCH_LIMIT)),
            as_json=bool(args.json),
        )
    if args.command == "index":
        target = Path(str(args.path)).expanduser()
        if not target.exists():
            print(f"error: path does not exist: {target}", file=sys.stderr)
            return 2
        raw_output: str = str(args.output)
        output: OutputMode = (
            "tree"
            if raw_output == "tree"
            else "nodes"
            if raw_output == "nodes"
            else "calls"
            if raw_output == "calls"
            else "summary"
        )
        scanned = await read(target.resolve())
        graph = build_graph(scanned.root, scanned.items)
        await out(
            db,
            scanned.root,
            graph,
            overwrite=bool(args.overwrite),
            output=output,
            quiet=bool(args.quiet),
            persist=bool(args.persist),
        )
        return 0
    return 2


def main(argv: list[str] | None = None) -> int:
    """Sync wrapper: run the async CLI."""
    return asyncio.run(amain(argv))


if __name__ == "__main__":
    raise SystemExit(main())
