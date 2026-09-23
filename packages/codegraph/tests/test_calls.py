"""Unit + e2e tests: call-edge resolution and indexing e2e."""

from __future__ import annotations

from pathlib import Path

import pytest

from codegraph.config import resolve_db
from codegraph.graph_store import create_store
from codegraph.parser import build_file_rows, resolve_call_edges
from codegraph.parser.base import ParsedCall, ParsedFile
from codegraph.pipeline import build_graph, out, print_calls, print_nodes, read


def test_resolve_call_edges_skips_unknown_caller() -> None:
    parsed = ParsedFile(
        language="python", calls=(ParsedCall(caller="nope", callee="g"),)
    )
    rows = build_file_rows("R", "a.py", "python", parsed)
    assert resolve_call_edges([rows], "R") == []


async def test_call_edges_e2e(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    src: Path = tmp_path / "src"
    src.mkdir()
    (src / "main.py").write_text(
        "from utils import helper\n\ndef run():\n    helper()\n", encoding="utf-8"
    )
    (src / "utils.py").write_text("def helper():\n    pass\n", encoding="utf-8")
    db = resolve_db((tmp_path / "g.lbdb").as_posix())
    scanned = await read(src)
    graph = build_graph(scanned.root, scanned.items)
    result = await out(db, scanned.root, graph, overwrite=True, quiet=True)
    assert await print_nodes(db, result.root) == 0
    out_text: str = capsys.readouterr().out
    assert "parent=main.py children=[] callees=[helper]" in out_text


async def test_placeholder_stub_e2e(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    src: Path = tmp_path / "src"
    src.mkdir()
    (src / "main.py").write_text(
        "from utils import helper, missing\n\ndef run():\n    helper()\n    missing()\n",
        encoding="utf-8",
    )
    (src / "utils.py").write_text("def helper():\n    pass\n", encoding="utf-8")
    db = resolve_db((tmp_path / "g.lbdb").as_posix())
    scanned = await read(src)
    graph = build_graph(scanned.root, scanned.items)
    result = await out(db, scanned.root, graph, overwrite=True, quiet=True)
    assert await print_calls(db, result.root) == 0
    out_text: str = capsys.readouterr().out
    assert "calls run -> helper  file=main.py" in out_text
    assert "calls run -> missing?  file=main.py" in out_text

    store = create_store(db.path)
    try:
        stubs = [n for n in await store.list_nodes() if n.is_placeholder]
    finally:
        await store.dispose()
    assert [(n.file_path, n.name) for n in stubs] == [("utils.py", "missing")]
