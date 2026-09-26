"""Unit + e2e tests: call-edge resolution and indexing e2e."""

from __future__ import annotations

from pathlib import Path

import pytest

from codegraph.config import resolve_db
from codegraph.graph_store import create_store
from codegraph.parser import FileRows, build_file_rows, resolve_call_edges
from codegraph.parser.lang_go import build_go_file_rows
from codegraph.parser.lang_typescript import build_ts_file_rows
from codegraph.parser.base import (
    ParsedCall,
    ParsedDefinition,
    ParsedFile,
    ParsedImport,
)
from codegraph.pipeline import build_graph, out, print_calls, print_nodes, read


def test_resolve_call_edges_skips_unknown_caller() -> None:
    parsed = ParsedFile(
        language="python", calls=(ParsedCall(caller="nope", callee="g"),)
    )
    rows = build_file_rows("R", "a.py", "python", parsed)
    assert resolve_call_edges([rows], "R") == []


def _two_file_rows(
    main_rel: str = "main.py",
    utils_rel: str = "utils.py",
    import_module: str = "utils",
    bound: str = "helper",
    original: str = "",
) -> tuple[FileRows, FileRows]:
    """Return ``(main, utils)`` rows: ``run()`` calls the imported name."""
    main = build_file_rows(
        "R",
        main_rel,
        "python",
        ParsedFile(
            language="python",
            definitions=(
                ParsedDefinition(
                    kind="function", name="run", start_line=1, end_line=4
                ),
            ),
            imports=(
                ParsedImport(
                    module=import_module,
                    name=bound,
                    start_line=1,
                    end_line=1,
                    original=original,
                ),
            ),
            calls=(ParsedCall(caller="run", callee=bound, site_line=3),),
            total_lines=4,
        ),
    )
    utils = build_file_rows(
        "R",
        utils_rel,
        "python",
        ParsedFile(
            language="python",
            definitions=(
                ParsedDefinition(
                    kind="function", name="helper", start_line=1, end_line=2
                ),
            ),
            total_lines=2,
        ),
    )
    return (main, utils)


def test_resolve_imported_call_joins_on_original_name() -> None:
    main, utils = _two_file_rows(bound="h", original="helper")
    edges = resolve_call_edges([main, utils], "R")
    assert len(edges) == 1
    by_id = {n.id: n for n in (*main.nodes, *utils.nodes)}
    assert by_id[edges[0].src_id].name == "run"
    assert by_id[edges[0].dst_id].name == "helper"
    assert edges[0].site_line == 3


def test_resolve_absolute_import_with_root_prefix() -> None:
    """Root-relative prefix on indexed paths must not break the join.

    Regression: indexed ``src/app/...`` vs specifier ``app....``.
    """
    main, utils = _two_file_rows(
        main_rel="src/app/main.py",
        utils_rel="src/app/utils.py",
        import_module="app.utils",
    )
    edges = resolve_call_edges([main, utils], "R")
    assert len(edges) == 1
    by_id = {n.id: n for n in (*main.nodes, *utils.nodes)}
    assert by_id[edges[0].dst_id].name == "helper"


def test_resolve_relative_import() -> None:
    main, utils = _two_file_rows(
        main_rel="pkg/main.py",
        utils_rel="pkg/utils.py",
        import_module=".utils",
    )
    edges = resolve_call_edges([main, utils], "R")
    assert len(edges) == 1


def test_resolve_ts_alias_and_default_imports() -> None:
    main = build_ts_file_rows(
        "R",
        "app/main.ts",
        'import { helper as h } from "./helper";\n'
        'import Runner from "./runner";\n'
        "export function run() {\n"
        "    h();\n"
        "    Runner();\n"
        "}\n",
        {},
    )
    helper = build_ts_file_rows(
        "R", "app/helper.ts", "export function helper() {}\n", {}
    )
    runner = build_ts_file_rows(
        "R", "app/runner.ts", "export default class Runner {}\n", {}
    )
    edges = resolve_call_edges([main, helper, runner], "R")
    by_id = {n.id: n for n in (*main.nodes, *helper.nodes, *runner.nodes)}
    pairs = {(by_id[e.src_id].name, by_id[e.dst_id].name) for e in edges}
    assert pairs == {("run", "helper"), ("run", "Runner")}
    assert by_id[[e for e in edges if by_id[e.dst_id].name == "helper"][0].dst_id].file_path == (
        "app/helper.ts"
    )


def test_resolve_ts_bare_specifier_dropped() -> None:
    main = build_ts_file_rows(
        "R",
        "a.ts",
        'import x from "mod";\nexport function f() { x(); }\n',
        {},
    )
    assert resolve_call_edges([main], "R") == []


def test_resolve_go_tail_and_dot_imports() -> None:
    main = build_go_file_rows(
        "R",
        "main.go",
        "package main\n"
        "\n"
        'import h "example.com/x/helper"\n'
        'import . "example.com/x/utils"\n'
        "\n"
        "func main() {\n"
        "\th()\n"
        "\tHelper()\n"
        "}\n",
        {},
    )
    helper = build_go_file_rows(
        "R", "lib/helper.go", "package helper\n\nfunc h() {}\n", {}
    )
    utils = build_go_file_rows(
        "R", "lib/utils.go", "package utils\n\nfunc Helper() {}\n", {}
    )
    edges = resolve_call_edges([main, helper, utils], "R")
    by_id = {n.id: n for n in (*main.nodes, *helper.nodes, *utils.nodes)}
    pairs = {
        (by_id[e.src_id].name, by_id[e.dst_id].name, by_id[e.dst_id].file_path)
        for e in edges
    }
    assert pairs == {
        ("main", "h", "lib/helper.go"),
        ("main", "Helper", "lib/utils.go"),
    }


def test_unresolvable_call_yields_no_edge() -> None:
    main = build_file_rows(
        "R",
        "a.py",
        "python",
        ParsedFile(
            language="python",
            definitions=(
                ParsedDefinition(
                    kind="function", name="run", start_line=1, end_line=4
                ),
            ),
            calls=(
                ParsedCall(caller="run", callee="native", site_line=2),
                ParsedCall(caller="run", callee="missing", site_line=3),
            ),
            total_lines=4,
        ),
    )
    assert resolve_call_edges([main], "R") == []


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


async def test_aliased_import_call_e2e(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    src: Path = tmp_path / "src"
    src.mkdir()
    (src / "main.py").write_text(
        "from utils import helper as h\n\ndef run():\n    h()\n", encoding="utf-8"
    )
    (src / "utils.py").write_text("def helper():\n    pass\n", encoding="utf-8")
    db = resolve_db((tmp_path / "g.lbdb").as_posix())
    scanned = await read(src)
    graph = build_graph(scanned.root, scanned.items)
    result = await out(db, scanned.root, graph, overwrite=True, quiet=True)
    assert await print_calls(db, result.root) == 0
    out_text: str = capsys.readouterr().out
    assert "calls run -> helper  file=main.py" in out_text


async def test_ts_cross_file_call_e2e(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    src: Path = tmp_path / "src"
    src.mkdir()
    (src / "helper.ts").write_text(
        "export function helper() {}\n", encoding="utf-8"
    )
    (src / "main.ts").write_text(
        'import { helper } from "./helper";\nexport function run() { helper(); }\n',
        encoding="utf-8",
    )
    db = resolve_db((tmp_path / "g.lbdb").as_posix())
    scanned = await read(src)
    graph = build_graph(scanned.root, scanned.items)
    result = await out(db, scanned.root, graph, overwrite=True, quiet=True)
    assert await print_calls(db, result.root) == 0
    out_text: str = capsys.readouterr().out
    assert "calls run -> helper  file=main.ts" in out_text


async def test_go_same_file_call_e2e(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    src: Path = tmp_path / "src"
    src.mkdir()
    (src / "main.go").write_text(
        "package main\n\nfunc Helper() {}\n\ntype S struct{}\n\n"
        "func (s *S) M() {\n\tHelper()\n}\n",
        encoding="utf-8",
    )
    db = resolve_db((tmp_path / "g.lbdb").as_posix())
    scanned = await read(src)
    graph = build_graph(scanned.root, scanned.items)
    result = await out(db, scanned.root, graph, overwrite=True, quiet=True)
    assert await print_calls(db, result.root) == 0
    out_text: str = capsys.readouterr().out
    assert "calls M -> Helper  file=main.go" in out_text


async def test_decorator_cross_file_call_e2e(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    src: Path = tmp_path / "src"
    src.mkdir()
    (src / "dec.py").write_text("def retry(fn):\n    return fn\n", encoding="utf-8")
    (src / "main.py").write_text(
        "from dec import retry\n\n\n@retry\ndef run():\n    pass\n",
        encoding="utf-8",
    )
    db = resolve_db((tmp_path / "g.lbdb").as_posix())
    scanned = await read(src)
    graph = build_graph(scanned.root, scanned.items)
    result = await out(db, scanned.root, graph, overwrite=True, quiet=True)
    assert await print_calls(db, result.root) == 0
    out_text: str = capsys.readouterr().out
    assert "calls run -> retry  file=main.py" in out_text


async def test_decorator_builtin_dropped_e2e(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    src: Path = tmp_path / "src"
    src.mkdir()
    (src / "main.py").write_text(
        "class S:\n    @property\n    def status(self):\n        return 1\n",
        encoding="utf-8",
    )
    db = resolve_db((tmp_path / "g.lbdb").as_posix())
    scanned = await read(src)
    graph = build_graph(scanned.root, scanned.items)
    result = await out(db, scanned.root, graph, overwrite=True, quiet=True)
    assert await print_calls(db, result.root) == 0
    out_text: str = capsys.readouterr().out
    assert "no calls for root" in out_text


async def test_unresolved_import_call_dropped_e2e(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
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
    assert "missing" not in out_text

    store = create_store(db.path)
    try:
        nodes = await store.list_nodes()
        edges = await store.list_edges()
    finally:
        await store.dispose()
    assert [n for n in nodes if n.is_placeholder] == []
    assert len([e for e in edges if str(e.kind.value) == "calls"]) == 1
