"""Unit + e2e tests: hierarchy-tree snapshot and rendering."""

from __future__ import annotations

from pathlib import Path

import pytest

from codegraph.cli import amain, print_nodes, print_tree, run_index
from codegraph.config import resolve_db
from codegraph.models import Edge, EdgeKind, Node, NodeKind
from codegraph.parser import build_graph_rows
from codegraph.parser.base import ParsedDefinition, ParsedFile
from codegraph.store import create_store
from codegraph.tree import GraphSnapshot, kind_label, load_snapshot, render_tree


def _node(
    node_id: str,
    kind: NodeKind,
    name: str,
    start: int,
    end: int,
    parent: str | None = None,
) -> Node:
    return Node(
        id=node_id,
        root="R",
        file_path="a.py",
        kind=kind,
        name=name,
        language="python",
        start_line=start,
        end_line=end,
        parent_id=parent,
    )


def _contains(src: str, dst: str) -> Edge:
    return Edge(id=f"{src}>{dst}", root="R", src_id=src, dst_id=dst,
                kind=EdgeKind.CONTAINS)


def _imports(src: str, dst: str, module: str) -> Edge:
    return Edge(id=f"{src}>{dst}", root="R", src_id=src, dst_id=dst,
                kind=EdgeKind.IMPORTS, target_module=module)


def _snapshot() -> GraphSnapshot:
    nodes = (
        _node("f1", NodeKind.FILE, "a.py", 1, 10),
        _node("c1", NodeKind.CLASS, "C", 4, 8, parent="f1"),
        _node("m1", NodeKind.FUNCTION, "m", 5, 6, parent="c1"),
        _node("fn1", NodeKind.FUNCTION, "f", 9, 10, parent="f1"),
        _node("i1", NodeKind.IMPORT, "os", 1, 1, parent="f1"),
    )
    edges = (
        _contains("f1", "c1"),
        _contains("f1", "fn1"),
        _contains("c1", "m1"),
        _imports("f1", "i1", "os"),
    )
    return GraphSnapshot(root="R", nodes=nodes, edges=edges)


def test_render_tree_exact() -> None:
    assert render_tree(_snapshot()) == (
        "root: R  (files=1 nodes=5 edges=4)\n"
        "file a.py [python] (L1-L10)\n"
        "├── class C (L4-L8)\n"
        "│   └── function m (L5-L6)\n"
        "├── function f (L9-L10)\n"
        "└── imports (1)\n"
        "    └── os -> os (L1)"
    )


def test_render_tree_empty() -> None:
    snapshot = GraphSnapshot(root="R", nodes=(), edges=())
    assert render_tree(snapshot) == "root: R  (files=0 nodes=0 edges=0)"


def test_render_tree_ascii() -> None:
    assert render_tree(_snapshot(), use_unicode=False) == (
        "root: R  (files=1 nodes=5 edges=4)\n"
        "file a.py [python] (L1-L10)\n"
        "|-- class C (L4-L8)\n"
        "|   `-- function m (L5-L6)\n"
        "|-- function f (L9-L10)\n"
        "`-- imports (1)\n"
        "    `-- os -> os (L1)"
    )


def test_render_tree_file_without_blocks() -> None:
    snapshot = GraphSnapshot(
        root="R",
        nodes=(_node("f1", NodeKind.FILE, "empty.py", 1, 1),),
        edges=(),
    )
    assert render_tree(snapshot) == (
        "root: R  (files=1 nodes=1 edges=0)\n"
        "file a.py [python] (L1-L1)"
    )


async def test_load_snapshot_roundtrip(tmp_path: Path) -> None:
    db = resolve_db((tmp_path / "g.db").as_posix())
    store = create_store(db.url)
    try:
        await store.create_all()
        snapshot_in = _snapshot()
        await store.add_all(list(snapshot_in.nodes), list(snapshot_in.edges))
        snapshot_out = await load_snapshot(store, "R")
    finally:
        await store.dispose()
    assert snapshot_out.root == "R"
    assert len(snapshot_out.nodes) == 5
    assert len(snapshot_out.edges) == 4
    assert "class C (L4-L8)" in render_tree(snapshot_out)


async def test_print_tree_e2e(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    src: Path = tmp_path / "src"
    src.mkdir()
    (src / "a.py").write_text(
        "import os\n\nclass C:\n    def m(self):\n        pass\n",
        encoding="utf-8",
    )
    db = resolve_db((tmp_path / "g.db").as_posix())
    result = await run_index(src, db, overwrite=True, quiet=True)
    assert await print_tree(db, result.root) == 0
    out: str = capsys.readouterr().out
    assert f"root: {result.root}" in out
    assert "file a.py [python]" in out
    assert "class C" in out
    assert "function m" in out
    assert "os -> os" in out


async def test_print_tree_empty_root(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    db = resolve_db((tmp_path / "g.db").as_posix())
    assert await print_tree(db, "missing-root") == 0
    assert "no nodes for root missing-root" in capsys.readouterr().out


async def test_amain_output_tree_flag(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    src: Path = tmp_path / "src"
    src.mkdir()
    (src / "a.py").write_text("def f():\n    pass\n", encoding="utf-8")
    db_path: Path = tmp_path / "g.db"
    code: int = await amain(
        ["index", src.as_posix(), "--db", db_path.as_posix(), "--output", "tree"]
    )
    assert code == 0
    out = capsys.readouterr().out
    assert "indexed 1 files" in out
    assert "function f (L1-L2)" in out


async def test_amain_default_output_is_summary(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    src: Path = tmp_path / "src"
    src.mkdir()
    (src / "a.py").write_text("def f():\n    pass\n", encoding="utf-8")
    db_path: Path = tmp_path / "g.db"
    code: int = await amain(["index", src.as_posix(), "--db", db_path.as_posix()])
    assert code == 0
    out = capsys.readouterr().out
    assert "indexed 1 files" in out
    assert "root:" not in out


def _nested_file() -> ParsedFile:
    """One file with a closure: f → g (caller → callee)."""
    return ParsedFile(
        language="python",
        definitions=(
            ParsedDefinition(kind="function", name="f", start_line=1, end_line=6),
            ParsedDefinition(
                kind="function", name="g", start_line=2, end_line=4, parent="f"
            ),
        ),
        total_lines=6,
    )


def test_build_graph_rows_emits_calls_edge() -> None:
    nodes, edges = build_graph_rows("R", "a.py", "python", _nested_file())
    kinds: dict[tuple[str, str], EdgeKind] = {}
    by_id: dict[str, Node] = {n.id: n for n in nodes}
    for edge in edges:
        kinds[(by_id[edge.src_id].name, by_id[edge.dst_id].name)] = (
            edge.kind if isinstance(edge.kind, EdgeKind) else EdgeKind(str(edge.kind))
        )
    assert kinds[("a.py", "f")] == EdgeKind.CONTAINS
    assert kinds[("f", "g")] == EdgeKind.CALLS
    # Caller side resolves through the stored node ids.
    calls = [e for e in edges if kind_label(e.kind) == "calls"]
    assert len(calls) == 1
    assert by_id[calls[0].src_id].name == "f"
    assert by_id[calls[0].dst_id].name == "g"


def test_build_graph_rows_skips_calls_for_methods() -> None:
    parsed = ParsedFile(
        language="python",
        definitions=(
            ParsedDefinition(kind="class", name="C", start_line=1, end_line=6),
            ParsedDefinition(
                kind="function", name="m", start_line=2, end_line=4,
                parent="C", is_method=True,
            ),
        ),
        total_lines=6,
    )
    _, edges = build_graph_rows("R", "a.py", "python", parsed)
    assert [e for e in edges if kind_label(e.kind) == "calls"] == []


def test_render_tree_calls_group() -> None:
    nodes, edges = build_graph_rows("R", "a.py", "python", _nested_file())
    snapshot = GraphSnapshot(root="R", nodes=tuple(nodes), edges=tuple(edges))
    assert render_tree(snapshot) == (
        "root: R  (files=1 nodes=3 edges=3)\n"
        "file a.py [python] (L1-L6)\n"
        "└── function f (L1-L6)\n"
        "    └── calls (1)\n"
        "        └── function g (L2-L4)"
    )


async def test_print_nodes_e2e(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    src: Path = tmp_path / "src"
    src.mkdir()
    (src / "a.py").write_text(
        "import os\n\ndef f():\n    def g():\n        pass\n",
        encoding="utf-8",
    )
    db = resolve_db((tmp_path / "g.db").as_posix())
    result = await run_index(src, db, overwrite=True, quiet=True)
    assert await print_nodes(db, result.root) == 0
    out: str = capsys.readouterr().out
    assert "parent=None children=[f, os]" in out  # file row
    assert "parent=a.py children=[g] callees=[g]" in out  # caller row
    assert "parent=f children=[] callees=[]" in out  # callee row
    assert "node import" in out and " os " in out


async def test_amain_output_nodes_flag(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    src: Path = tmp_path / "src"
    src.mkdir()
    (src / "a.py").write_text("def f():\n    pass\n", encoding="utf-8")
    db_path: Path = tmp_path / "g.db"
    code: int = await amain(
        ["index", src.as_posix(), "--db", db_path.as_posix(), "--output", "nodes"]
    )
    assert code == 0
    out = capsys.readouterr().out
    assert "node function f" in out
    assert "parent=a.py children=[] callees=[]" in out
