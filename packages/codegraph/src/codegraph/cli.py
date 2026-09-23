"""Sentinel code graph CLI (fully async, I/O at the edge).

Flow: ``amain`` parses args, then ``pipeline.read -> pipeline.build_graph
-> pipeline.out``. Tree-sitter parsing runs on the event-loop thread
(``Parser`` / ``Tree`` / ``Node`` are not thread-safe); only file I/O
goes through ``to_thread``.

Usage:
    codegraph index <path> --db ./codegraph.lbdb [--overwrite] [--quiet]
        [--output {summary,tree,nodes,calls}] [--persist | --no-persist]
    codegraph stats --db ./codegraph.lbdb
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from codegraph.config import ResolvedDb, resolve_db
from codegraph.graph_store import create_store
from codegraph.pipeline import OutputMode, build_graph, out, read


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
        "--db",
        default="./codegraph.lbdb",
        help="Ladybug database path or :memory:",
    )
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
    stats_cmd.add_argument(
        "--db",
        default="./codegraph.lbdb",
        help="Ladybug database path or :memory:",
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
