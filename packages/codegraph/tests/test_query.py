"""Unit + e2e tests: agent-facing query verbs and the default DB."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from codegraph.cli import amain, run_query
from codegraph.config import resolve_db
from codegraph.pipeline import build_graph, out, read
from codegraph.query import (
    DEFAULT_SEARCH_LIMIT,
    envelope,
    exact_matches,
    search_nodes,
    to_item,
)
from codegraph.tree import kind_label


async def _write_fixture(src: Path) -> None:
    src.mkdir()
    (src / "main.py").write_text(
        "from utils import helper as h\n\ndef run():\n    h()\n", encoding="utf-8"
    )
    (src / "utils.py").write_text("def helper():\n    pass\n", encoding="utf-8")
    (src / "shapes.ts").write_text(
        "export interface I { m(): void; }\n"
        "export type A = string;\n"
        'import { helper } from "./helper";\n'
        "export function run() { helper(); }\n",
        encoding="utf-8",
    )
    (src / "helper.ts").write_text(
        "export function helper() {}\n", encoding="utf-8"
    )


async def _indexed_db(tmp_path: Path) -> Any:
    """Index the fixture; return the resolved db."""
    src: Path = tmp_path / "src"
    await _write_fixture(src)
    db = resolve_db((tmp_path / "q.lbdb").as_posix())
    scanned = await read(src)
    graph = build_graph(scanned.root, scanned.items)
    await out(db, scanned.root, graph, overwrite=True, quiet=True)
    return db


async def test_missing_db_errors_without_creating(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    missing: str = (tmp_path / "nope" / "q.lbdb").as_posix()
    assert await amain(["stats", "--db", missing]) == 1
    assert "no database at" in capsys.readouterr().err
    assert await amain(["query", "--db", missing, "overview"]) == 1
    assert "run `codegraph index` first" in capsys.readouterr().err
    assert not (tmp_path / "nope" / "q.lbdb").exists()


async def test_query_overview(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    db = await _indexed_db(tmp_path)
    assert (
        await run_query(
            db,
            root_filter=None,
            verb="overview",
            node_id=None,
            name=None,
            file=None,
            kind=None,
            limit=DEFAULT_SEARCH_LIMIT,
            as_json=False,
        )
        == 0
    )
    human: str = capsys.readouterr().out
    assert "files: 4" in human
    assert "interface=1" in human


async def test_query_overview_json(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    db = await _indexed_db(tmp_path)
    assert (
        await run_query(
            db,
            root_filter=None,
            verb="overview",
            node_id=None,
            name=None,
            file=None,
            kind=None,
            limit=DEFAULT_SEARCH_LIMIT,
            as_json=True,
        )
        == 0
    )
    payload: dict[str, Any] = json.loads(capsys.readouterr().out)
    assert payload["verb"] == "overview"
    assert payload["files"] == 4
    assert payload["by_language"]["python"] == 2
    assert payload["by_language"]["typescript"] == 2


async def test_query_files_and_search_ladder(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    db = await _indexed_db(tmp_path)
    assert (
        await run_query(
            db,
            root_filter=None,
            verb="files",
            node_id=None,
            name=None,
            file=None,
            kind=None,
            limit=DEFAULT_SEARCH_LIMIT,
            as_json=True,
        )
        == 0
    )
    files_payload: dict[str, Any] = json.loads(capsys.readouterr().out)
    assert {i["file_path"] for i in files_payload["items"]} == {
        "main.py",
        "utils.py",
        "shapes.ts",
        "helper.ts",
    }
    # Agent turns a vague name into ids via search ...
    assert (
        await run_query(
            db,
            root_filter=None,
            verb="search",
            node_id=None,
            name="RUN",
            file=None,
            kind="function",
            limit=DEFAULT_SEARCH_LIMIT,
            as_json=True,
        )
        == 0
    )
    search_payload: dict[str, Any] = json.loads(capsys.readouterr().out)
    assert search_payload["count"] == 2  # main.py run + shapes.ts run
    assert search_payload["truncated"] is False
    assert {i["file_path"] for i in search_payload["items"]} == {
        "main.py",
        "shapes.ts",
    }
    # ... then drills with a discovered id.
    run_id: str = next(
        i["id"] for i in search_payload["items"] if i["file_path"] == "main.py"
    )
    assert (
        await run_query(
            db,
            root_filter=None,
            verb="callees",
            node_id=run_id,
            name=None,
            file=None,
            kind=None,
            limit=DEFAULT_SEARCH_LIMIT,
            as_json=True,
        )
        == 0
    )
    callees_payload: dict[str, Any] = json.loads(capsys.readouterr().out)
    assert [(i["name"], i["file_path"]) for i in callees_payload["items"]] == [
        ("helper", "utils.py")
    ]


async def test_query_search_truncation_and_filters(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    db = await _indexed_db(tmp_path)
    assert (
        await run_query(
            db,
            root_filter=None,
            verb="search",
            node_id=None,
            name="e",
            file=None,
            kind=None,
            limit=1,
            as_json=True,
        )
        == 0
    )
    payload: dict[str, Any] = json.loads(capsys.readouterr().out)
    assert payload["count"] == 1
    assert payload["truncated"] is True
    assert (
        await run_query(
            db,
            root_filter=None,
            verb="search",
            node_id=None,
            name="zzz-no-such-def",
            file=None,
            kind=None,
            limit=DEFAULT_SEARCH_LIMIT,
            as_json=True,
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["count"] == 0
    assert (
        await run_query(
            db,
            root_filter=None,
            verb="search",
            node_id=None,
            name="helper",
            file="helper.ts",
            kind=None,
            limit=DEFAULT_SEARCH_LIMIT,
            as_json=False,
        )
        == 0
    )
    assert "file=helper.ts" in capsys.readouterr().out


async def test_query_name_sugar_ambiguity(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    db = await _indexed_db(tmp_path)
    code: int = await run_query(
        db,
        root_filter=None,
        verb="node",
        node_id=None,
        name="run",
        file=None,
        kind=None,
        limit=DEFAULT_SEARCH_LIMIT,
        as_json=False,
    )
    assert code == 1
    err: str = capsys.readouterr().err
    assert "ambiguous name 'run' (2 hits)" in err
    assert (
        await run_query(
            db,
            root_filter=None,
            verb="node",
            node_id=None,
            name="run",
            file="shapes.ts",
            kind=None,
            limit=DEFAULT_SEARCH_LIMIT,
            as_json=False,
        )
        == 0
    )
    assert "function run" in capsys.readouterr().out
    assert (
        await run_query(
            db,
            root_filter=None,
            verb="callers",
            node_id=None,
            name="helper",
            file="utils.py",
            kind=None,
            limit=DEFAULT_SEARCH_LIMIT,
            as_json=False,
        )
        == 0
    )
    assert "function run" in capsys.readouterr().out


async def test_query_children_and_imports(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    db = await _indexed_db(tmp_path)
    assert (
        await run_query(
            db,
            root_filter=None,
            verb="children",
            node_id="main.py",
            name=None,
            file=None,
            kind=None,
            limit=DEFAULT_SEARCH_LIMIT,
            as_json=False,
        )
        == 0
    )
    assert "function run" in capsys.readouterr().out
    assert (
        await run_query(
            db,
            root_filter=None,
            verb="imports",
            node_id=None,
            name=None,
            file="main.py",
            kind=None,
            limit=DEFAULT_SEARCH_LIMIT,
            as_json=False,
        )
        == 0
    )
    out_text: str = capsys.readouterr().out
    assert "import h" in out_text
    assert "-> utils" in out_text
    assert (
        await run_query(
            db,
            root_filter=None,
            verb="node",
            node_id="no-such-id",
            name=None,
            file=None,
            kind=None,
            limit=DEFAULT_SEARCH_LIMIT,
            as_json=False,
        )
        == 1
    )
    assert "no node with id" in capsys.readouterr().err


async def test_query_root_narrowing(tmp_path: Path) -> None:
    first: Path = tmp_path / "first"
    first.mkdir()
    (first / "a.py").write_text("def f():\n    pass\n", encoding="utf-8")
    second: Path = tmp_path / "second"
    second.mkdir()
    (second / "b.py").write_text("def g():\n    pass\n", encoding="utf-8")
    db = resolve_db((tmp_path / "q.lbdb").as_posix())
    for target, overwrite in ((first, True), (second, False)):
        scanned = await read(target)
        graph = build_graph(scanned.root, scanned.items)
        await out(db, scanned.root, graph, overwrite=overwrite, quiet=True)
    both = await _files_count(db, None)
    assert both == 2
    assert await _files_count(db, (tmp_path / "second").resolve().as_posix()) == 1


async def _files_count(db: Any, root_filter: str | None) -> int:
    from codegraph.graph_store import create_store

    store = create_store(db.path)
    try:
        await store.create_all()
        return len(await store.list_files(root_filter))
    finally:
        await store.dispose()


def test_search_nodes_pure() -> None:
    from codegraph.models import Node, NodeKind

    def _node(node_id: str, kind: NodeKind, name: str, file_path: str) -> Node:
        return Node(
            id=node_id,
            root="R",
            file_path=file_path,
            kind=kind,
            name=name,
            language="python",
            start_line=1,
            end_line=2,
        )

    nodes: list[Node] = [
        _node("f", NodeKind.FILE, "a.py", "a.py"),
        _node("d1", NodeKind.FUNCTION, "run", "a.py"),
        _node("d2", NodeKind.FUNCTION, "Runner", "b.py"),
        _node("d3", NodeKind.CLASS, "run", "c.py"),
    ]
    hits, truncated = search_nodes(nodes, "run")
    assert [n.id for n in hits] == ["d1", "d2", "d3"]  # files never match
    assert truncated is False
    hits, _ = search_nodes(nodes, "run", kind="CLASS")
    assert [n.id for n in hits] == ["d3"]
    hits, truncated = search_nodes(nodes, "run", limit=2)
    assert [n.id for n in hits] == ["d1", "d2"]
    assert truncated is True
    assert [n.id for n in exact_matches(nodes, "run")] == ["d1", "d3"]
    item = to_item(hits[0])
    assert item["id"] == "d1" and item["kind"] == "function"
    payload = envelope("R", "search", [item])
    assert payload["count"] == 1 and payload["verb"] == "search"
    assert kind_label(hits[0].kind) == "function"
