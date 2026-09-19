"""Unit + e2e tests: query-only call-site extraction and cross-file resolution."""

from __future__ import annotations

from pathlib import Path

import pytest

from codegraph.cli import print_nodes, run_index
from codegraph.config import resolve_db
from codegraph.models import Edge
from codegraph.parser import FileRows, build_file_rows, parse_source_text, resolve_call_edges
from codegraph.parser.base import ParsedCall, ParsedFile
from codegraph.parser.calls import extract_calls
from codegraph.tree import kind_label


def _rows(rel_path: str, language: str, source: str) -> FileRows:
    """Parse real source text and build per-file rows."""
    return build_file_rows(
        "R", rel_path, language, parse_source_text(language, source)
    )


def _call_pairs(files: list[FileRows], edges: list[Edge]) -> set[tuple[str, str]]:
    by_id: dict[str, str] = {n.id: n.name for rows in files for n in rows.nodes}
    return {
        (by_id[e.src_id], by_id[e.dst_id])
        for e in edges
        if kind_label(e.kind) == "calls"
    }


def test_extract_calls_python_basic() -> None:
    calls: list[ParsedCall] = extract_calls(
        "python", b"def f():\n    g()\n\ndef g():\n    pass\n"
    )
    assert calls == [ParsedCall(caller="f", callee="g")]


def test_extract_calls_python_drops_module_level() -> None:
    calls = extract_calls("python", b"g()\n\ndef g():\n    pass\n")
    assert calls == []


def test_extract_calls_python_method_caller() -> None:
    source = b"class C:\n    def m(self):\n        helper()\n"
    assert extract_calls("python", source) == [ParsedCall(caller="m", callee="helper")]


def test_extract_calls_python_closure_caller() -> None:
    source = b"def f():\n    def g():\n        h()\n"
    assert extract_calls("python", source) == [ParsedCall(caller="g", callee="h")]


def test_extract_calls_python_ignores_attribute_calls() -> None:
    source = b"def f(self):\n    self.x()\n    obj.method()\n    plain()\n"
    assert extract_calls("python", source) == [ParsedCall(caller="f", callee="plain")]


def test_extract_calls_unknown_language() -> None:
    assert extract_calls("ruby", b"puts 1\n") == []


def test_extract_calls_typescript_named_and_arrow() -> None:
    source = (
        "function f(): void {\n"
        "    g();\n"
        "}\n"
        "const h = (): void => {\n"
        "    g();\n"
        "};\n"
    ).encode("utf-8")
    calls = extract_calls("typescript", source)
    assert ParsedCall(caller="f", callee="g") in calls
    assert ParsedCall(caller="h", callee="g") in calls


def test_extract_calls_typescript_method_caller() -> None:
    source = b"class C {\n    m(): void {\n        helper();\n    }\n}\n"
    assert extract_calls("typescript", source) == [
        ParsedCall(caller="m", callee="helper")
    ]


def test_resolve_call_edges_same_file() -> None:
    rows: FileRows = _rows("a.py", "python", "def f():\n    g()\n\ndef g():\n    pass\n")
    assert _call_pairs([rows], resolve_call_edges([rows], "R")) == {("f", "g")}


def test_resolve_call_edges_cross_file_absolute_import() -> None:
    main: FileRows = _rows(
        "pkg/main.py",
        "python",
        "from pkg.utils import helper\n\ndef run():\n    helper()\n",
    )
    utils: FileRows = _rows("pkg/utils.py", "python", "def helper():\n    pass\n")
    assert _call_pairs([main, utils], resolve_call_edges([main, utils], "R")) == {
        ("run", "helper")
    }


def test_resolve_call_edges_module_rooted_above_index() -> None:
    main = _rows(
        "steps/main.py",
        "python",
        "from app.proj.steps.utils import helper\n\ndef run():\n    helper()\n",
    )
    utils = _rows("steps/utils.py", "python", "def helper():\n    pass\n")
    assert _call_pairs([main, utils], resolve_call_edges([main, utils], "R")) == {
        ("run", "helper")
    }


def test_resolve_call_edges_cross_file_relative_import() -> None:
    main = _rows(
        "pkg/main.py",
        "python",
        "from .utils import helper\n\ndef run():\n    helper()\n",
    )
    utils = _rows("pkg/utils.py", "python", "def helper():\n    pass\n")
    assert _call_pairs([main, utils], resolve_call_edges([main, utils], "R")) == {
        ("run", "helper")
    }


def test_resolve_call_edges_skips_builtins_and_unknown() -> None:
    rows = _rows(
        "a.py", "python", "def f():\n    n = len([1])\n    missing()\n"
    )
    assert resolve_call_edges([rows], "R") == []


def test_resolve_call_edges_dedupes_repeat_sites() -> None:
    rows = _rows(
        "a.py", "python", "def f():\n    g()\n    g()\n\ndef g():\n    pass\n"
    )
    assert _call_pairs([rows], resolve_call_edges([rows], "R")) == {("f", "g")}


def test_resolve_call_edges_class_instantiation() -> None:
    main = _rows(
        "pkg/main.py",
        "python",
        "from pkg.errors import CloneError\n\ndef run():\n    raise CloneError()\n",
    )
    errors = _rows("pkg/errors.py", "python", "class CloneError(Exception):\n    pass\n")
    assert _call_pairs([main, errors], resolve_call_edges([main, errors], "R")) == {
        ("run", "CloneError")
    }


def test_resolve_call_edges_skips_unknown_caller() -> None:
    parsed = ParsedFile(
        language="python", calls=(ParsedCall(caller="nope", callee="g"),)
    )
    rows = build_file_rows("R", "a.py", "python", parsed)
    assert resolve_call_edges([rows], "R") == []


def test_resolve_call_edges_typescript_relative_import() -> None:
    app = _rows(
        "src/app.ts",
        "typescript",
        'import { load } from "./loader";\n\nfunction boot(): void {\n    load();\n}\n',
    )
    loader = _rows(
        "src/loader.ts", "typescript", "export function load(): void {}\n"
    )
    assert _call_pairs([app, loader], resolve_call_edges([app, loader], "R")) == {
        ("boot", "load")
    }


async def test_call_edges_e2e(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    src: Path = tmp_path / "src"
    src.mkdir()
    (src / "main.py").write_text(
        "from utils import helper\n\ndef run():\n    helper()\n", encoding="utf-8"
    )
    (src / "utils.py").write_text("def helper():\n    pass\n", encoding="utf-8")
    db = resolve_db((tmp_path / "g.db").as_posix())
    result = await run_index(src, db, overwrite=True, quiet=True)
    assert await print_nodes(db, result.root) == 0
    out: str = capsys.readouterr().out
    assert "parent=main.py children=[] callees=[helper]" in out
