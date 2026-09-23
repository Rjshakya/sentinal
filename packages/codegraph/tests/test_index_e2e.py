"""End-to-end tests: index a fixture tree into Ladybug and verify."""

from __future__ import annotations

from pathlib import Path

import pytest

from codegraph.cli import run_stats
from codegraph.config import resolve_db
from codegraph.graph_store import create_store
from codegraph.pipeline import build_graph, out, read


def _write_tree(root: Path) -> None:
    (root / "a.py").write_text(
        "import os\n\nclass C:\n    def m(self):\n        pass\n",
        encoding="utf-8",
    )
    (root / "b.ts").write_text(
        'import x from "mod";\nexport function f() {}\n',
        encoding="utf-8",
    )
    (root / "c.go").write_text(
        "package main\n\nfunc greet() {}\n",
        encoding="utf-8",
    )
    (root / "ignore.txt").write_text("not source\n", encoding="utf-8")
    (root / "node_modules").mkdir()
    (root / "node_modules" / "skip.js").write_text("function s() {}\n", encoding="utf-8")


async def test_index_e2e(tmp_path: Path) -> None:
    src: Path = tmp_path / "src"
    src.mkdir()
    _write_tree(src)
    db_path: Path = tmp_path / "graph.lbdb"

    db = resolve_db(db_path.as_posix())
    scanned = await read(src)
    graph = build_graph(scanned.root, scanned.items)
    result = await out(db, scanned.root, graph, overwrite=True, quiet=True)
    assert result.files == 3
    assert result.skipped == 0
    assert result.nodes > result.files
    assert result.edges > 0

    store = create_store(resolve_db(db_path.as_posix()).path)
    try:
        files, nodes, edges = await store.total_counts()
        assert files == 3
        # No dangling refs in this fixture: nothing to stub.
        assert nodes == result.nodes
        assert edges == result.edges
        by_kind = await store.count_by_node_kind()
        assert by_kind.get("file", 0) == 3
        by_lang = await store.count_by_language()
        assert by_lang == {"go": 1, "python": 1, "typescript": 1}
    finally:
        await store.dispose()


async def test_index_idempotent_overwrite(tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir()
    _write_tree(src)
    db_path = tmp_path / "graph.lbdb"
    db = resolve_db(db_path.as_posix())

    async def run_once() -> tuple[int, int]:
        scanned = await read(src)
        graph = build_graph(scanned.root, scanned.items)
        result = await out(db, scanned.root, graph, overwrite=True, quiet=True)
        return (result.nodes, result.edges)

    assert await run_once() == await run_once()


async def test_overwrite_flushes_whole_db(tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir()
    _write_tree(src)
    db = resolve_db((tmp_path / "graph.lbdb").as_posix())
    scanned = await read(src)
    graph = build_graph(scanned.root, scanned.items)
    await out(db, scanned.root, graph, overwrite=True, quiet=True)

    other = tmp_path / "other"
    other.mkdir()
    (other / "solo.py").write_text("def f():\n    pass\n", encoding="utf-8")
    scanned_other = await read(other)
    graph_other = build_graph(scanned_other.root, scanned_other.items)
    await out(db, scanned_other.root, graph_other, overwrite=True, quiet=True)

    store = create_store(db.path)
    try:
        files, _, _ = await store.total_counts()
        by_lang = await store.count_by_language()
    finally:
        await store.dispose()
    assert files == 1
    assert by_lang == {"python": 1}


async def test_index_single_file(tmp_path: Path) -> None:
    target = tmp_path / "only.py"
    target.write_text("def f():\n    pass\n", encoding="utf-8")
    db = resolve_db((tmp_path / "graph.lbdb").as_posix())
    scanned = await read(target)
    graph = build_graph(scanned.root, scanned.items)
    result = await out(db, scanned.root, graph, overwrite=True, quiet=True)
    assert result.files == 1
    assert result.nodes == 2  # file + function
    assert result.edges == 1  # contains


async def test_memory_db_renders_in_single_out(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    src: Path = tmp_path / "src"
    src.mkdir()
    (src / "a.py").write_text("def f():\n    pass\n", encoding="utf-8")
    db = resolve_db(":memory:")
    scanned = await read(src)
    graph = build_graph(scanned.root, scanned.items)
    result = await out(
        db, scanned.root, graph, overwrite=True, quiet=True, output="nodes"
    )
    assert result.files == 1
    assert "node function f" in capsys.readouterr().out


async def test_stats_runs(tmp_path: Path) -> None:
    src: Path = tmp_path / "src"
    src.mkdir()
    _write_tree(src)
    db = resolve_db((tmp_path / "graph.lbdb").as_posix())
    scanned = await read(src)
    graph = build_graph(scanned.root, scanned.items)
    await out(db, scanned.root, graph, overwrite=True, quiet=True)
    assert await run_stats(db) == 0
