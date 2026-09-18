"""End-to-end tests: index a fixture tree into SQLite and verify."""

from __future__ import annotations

from pathlib import Path

from codegraph.cli import run_index, run_stats
from codegraph.config import resolve_db
from codegraph.store import create_store


def _write_tree(root: Path) -> None:
    (root / "a.py").write_text(
        "import os\n\nclass C:\n    def m(self):\n        pass\n",
        encoding="utf-8",
    )
    (root / "b.ts").write_text(
        'import x from "mod";\nexport function f() {}\n',
        encoding="utf-8",
    )
    (root / "ignore.txt").write_text("not source\n", encoding="utf-8")
    (root / "node_modules").mkdir()
    (root / "node_modules" / "skip.js").write_text("function s() {}\n", encoding="utf-8")


async def test_index_e2e(tmp_path: Path) -> None:
    src: Path = tmp_path / "src"
    src.mkdir()
    _write_tree(src)
    db_path: Path = tmp_path / "graph.db"

    result = await run_index(
        src, resolve_db(db_path.as_posix()), overwrite=True, quiet=True
    )
    assert result.files == 2
    assert result.skipped == 0
    assert result.nodes > result.files
    assert result.edges > 0

    store = create_store(resolve_db(db_path.as_posix()).url)
    try:
        files, nodes, edges = await store.total_counts()
        assert files == 2
        assert nodes == result.nodes
        assert edges == result.edges
        by_kind = await store.count_by_node_kind()
        assert by_kind.get("file", 0) == 2
        by_lang = await store.count_by_language()
        assert by_lang.get("python", 0) == 1
        assert by_lang.get("typescript", 0) == 1
    finally:
        await store.dispose()


async def test_index_idempotent_overwrite(tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir()
    _write_tree(src)
    db_path = tmp_path / "graph.db"
    db = resolve_db(db_path.as_posix())

    first = await run_index(src, db, overwrite=True, quiet=True)
    second = await run_index(src, db, overwrite=True, quiet=True)
    assert (first.nodes, first.edges) == (second.nodes, second.edges)


async def test_index_single_file(tmp_path: Path) -> None:
    target = tmp_path / "only.py"
    target.write_text("def f():\n    pass\n", encoding="utf-8")
    db = resolve_db((tmp_path / "graph.db").as_posix())
    result = await run_index(target, db, overwrite=True, quiet=True)
    assert result.files == 1
    assert result.nodes == 2  # file + function
    assert result.edges == 1  # contains


async def test_stats_runs(tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir()
    _write_tree(src)
    db = resolve_db((tmp_path / "graph.db").as_posix())
    await run_index(src, db, overwrite=True, quiet=True)
    assert await run_stats(db) == 0
