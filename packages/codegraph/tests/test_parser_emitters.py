"""Emitter unit tests: per-language collect phases.

Each language implements ``collect_<lang>_file`` (defs + imports with
alias originals + buffered call sites, no ``calls`` edges —
resolution lives in the link phase). These tests pin the node id
shapes, the collect contract (buffered sites, alias originals,
native / module-level / attribute drops), and each grammar's own
defs, imports, and call shapes.
"""

from __future__ import annotations

from typing import Any

from codegraph.models import EdgeKind, Node, NodeKind
from codegraph.parser import lang_go, lang_python, lang_typescript
from codegraph.parser.raw_core import parse


_DEF_KINDS: tuple[NodeKind, ...] = (
    NodeKind.CLASS,
    NodeKind.METHOD,
    NodeKind.FUNCTION,
    NodeKind.INTERFACE,
    NodeKind.TYPE,
)


def _defs_by_name(out: Any) -> dict[str, Node]:
    found: dict[str, Node] = {}
    for node in out.nodes.values():
        if node.kind in _DEF_KINDS:
            found.setdefault(node.name, node)
    return found


def _buffered_calls(out: Any) -> list[tuple[str, str, int | None]]:
    return [(c.caller, c.callee, c.site_line) for c in out.calls]


def _no_calls_edges(out: Any) -> None:
    assert [e for e in out.edges if e.kind == EdgeKind.CALLS] == []


def _import_edges(out: Any) -> list[tuple[str, str | None]]:
    by_id: dict[str, Node] = out.nodes
    return [
        (by_id[edge.dst_id].name, edge.target_module)
        for edge in out.edges
        if edge.kind == EdgeKind.IMPORTS
    ]


def test_python_id_shapes() -> None:
    assert lang_python.build_defined_node_id("a.py", "f", 1, 2) == "a.py:f:1:2"


def test_python_collect_buffers_calls_and_alias_originals() -> None:
    src = "from utils import helper as h\n\ndef run():\n    h()\n    unknown()\n"
    tree = parse("python", src.encode("utf-8"))
    out = lang_python.collect_python_file("main.py", tree.root_node, "R", 5)
    assert out.definitions["run"] == lang_python.build_defined_node_id(
        "main.py", "run", 3, 5
    )
    assert [(i.name, i.effective_original, i.module) for i in out.imports] == [
        ("h", "helper", "utils")
    ]
    assert [(c.caller, c.callee, c.site_line) for c in out.calls] == [
        ("run", "h", 4),
        ("run", "unknown", 5),
    ]
    assert [e for e in out.edges if e.kind == EdgeKind.CALLS] == []
    assert _import_edges(out) == [("h", "utils")]


def test_typescript_defs_imports_calls() -> None:
    src = (
        'import x from "mod";\n'
        'import {a, b as c} from "m2";\n'
        "export class C { m() { helper(); } }\n"
        "export function f() { g(); }\n"
        "const g = () => { f(); };\n"
    )
    tree = parse("typescript", src.encode("utf-8"))
    out = lang_typescript.collect_ts_file("a.ts", tree.root_node, "R", 6)
    defs = _defs_by_name(out)
    assert (defs["C"].kind, defs["m"].kind) == (NodeKind.CLASS, NodeKind.METHOD)
    assert (defs["f"].kind, defs["g"].kind) == (
        NodeKind.FUNCTION,
        NodeKind.FUNCTION,
    )
    assert defs["m"].parent_id == defs["C"].id
    assert sorted(_import_edges(out)) == [("a", "m2"), ("c", "m2"), ("x", "mod")]
    assert [(i.name, i.effective_original) for i in out.imports] == [
        ("x", "x"),
        ("a", "a"),
        ("c", "b"),
    ]
    assert {(caller, callee) for caller, callee, _ in _buffered_calls(out)} == {
        ("m", "helper"),
        ("f", "g"),
        ("g", "f"),
    }
    assert {(caller, site) for caller, _, site in _buffered_calls(out)} == {
        ("m", 3),
        ("f", 4),
        ("g", 5),
    }
    _no_calls_edges(out)


def test_typescript_interface_type_and_new() -> None:
    src = (
        'import { helper } from "./helper";\n'
        "export interface I { m(): void; }\n"
        "export type A = string;\n"
        "export class C { m() { helper(); const x = new Foo(); } }\n"
    )
    tree = parse("typescript", src.encode("utf-8"))
    out = lang_typescript.collect_ts_file("a.ts", tree.root_node, "R", 4)
    defs = _defs_by_name(out)
    assert defs["I"].kind == NodeKind.INTERFACE
    assert defs["A"].kind == NodeKind.TYPE
    assert defs["C"].kind == NodeKind.CLASS
    methods = [
        n
        for n in out.nodes.values()
        if n.kind == NodeKind.METHOD and n.name == "m"
    ]
    assert len(methods) == 2
    assert {m.parent_id for m in methods} == {defs["I"].id, defs["C"].id}
    assert {(caller, callee) for caller, callee, _ in _buffered_calls(out)} == {
        ("m", "helper"),
        ("m", "Foo"),
    }
    _no_calls_edges(out)


def test_typescript_imported_call_buffered_for_link() -> None:
    src = 'import { helper } from "./helper";\nexport function run() { helper(); }\n'
    tree = parse("typescript", src.encode("utf-8"))
    out = lang_typescript.collect_ts_file("a.ts", tree.root_node, "R", 2)
    assert _buffered_calls(out) == [("run", "helper", 2)]
    _no_calls_edges(out)


def test_typescript_bare_specifier_call_buffered() -> None:
    src = 'import x from "mod";\nexport function f() { x(); }\n'
    tree = parse("typescript", src.encode("utf-8"))
    out = lang_typescript.collect_ts_file("a.ts", tree.root_node, "R", 2)
    # Buffered here; the link phase drops it (npm specifier, no file).
    assert _buffered_calls(out) == [("f", "x", 2)]
    _no_calls_edges(out)
    assert _import_edges(out) == [("x", "mod")]


def test_typescript_module_level_and_attribute_calls_dropped() -> None:
    src = 'import o from "./o";\no.method();\nbare();\n'
    tree = parse("typescript", src.encode("utf-8"))
    out = lang_typescript.collect_ts_file("a.ts", tree.root_node, "R", 3)
    assert _buffered_calls(out) == []
    _no_calls_edges(out)


def test_typescript_side_effect_import() -> None:
    tree = parse("typescript", b'import "./polyfill";\n')
    out = lang_typescript.collect_ts_file("a.ts", tree.root_node, "R", 1)
    assert _import_edges(out) == [("*", "./polyfill")]


def test_javascript_uses_javascript_grammar() -> None:
    rows = lang_typescript.build_ts_file_rows(
        "R", "b.jsx", "const g = () => {};\n", {}
    )
    assert rows.language == "javascript"
    assert [n.name for n in rows.nodes if n.kind == NodeKind.FUNCTION] == ["g"]
    rows_ts = lang_typescript.build_ts_file_rows(
        "R", "b.ts", "const g = () => {};\n", {}
    )
    assert rows_ts.language == "typescript"


def test_go_struct_method_func_and_imports() -> None:
    src = (
        "package main\n"
        "\n"
        "import (\n"
        '\t"fmt"\n'
        '\talias "example.com/x/utils"\n'
        '\t_ "os"\n'
        ")\n"
        "\n"
        "func Helper() {}\n"
        "\n"
        "type S struct {\n"
        "\tX int\n"
        "}\n"
        "\n"
        "func (s *S) M() {\n"
        "\tHelper()\n"
        "}\n"
    )
    tree = parse("go", src.encode("utf-8"))
    out = lang_go.collect_go_file("a.go", tree.root_node, "R", 17)
    defs = _defs_by_name(out)
    assert (defs["Helper"].kind, defs["S"].kind, defs["M"].kind) == (
        NodeKind.FUNCTION,
        NodeKind.CLASS,
        NodeKind.METHOD,
    )
    assert defs["M"].parent_id == defs["S"].id
    assert sorted(_import_edges(out)) == [
        ("*", "os"),
        ("alias", "example.com/x/utils"),
        ("fmt", "fmt"),
    ]
    assert _buffered_calls(out) == [("M", "Helper", 16)]
    _no_calls_edges(out)


def test_go_interface_and_type_collected() -> None:
    src = (
        "package p\n"
        "\n"
        "type I interface {\n"
        "\tM()\n"
        "\tN(x int) string\n"
        "}\n"
        "\n"
        "type A int\n"
        "\n"
        "type S struct{}\n"
    )
    tree = parse("go", src.encode("utf-8"))
    out = lang_go.collect_go_file("a.go", tree.root_node, "R", 11)
    defs = _defs_by_name(out)
    assert defs["I"].kind == NodeKind.INTERFACE
    assert defs["A"].kind == NodeKind.TYPE
    assert defs["S"].kind == NodeKind.CLASS
    methods = [
        n
        for n in out.nodes.values()
        if n.kind == NodeKind.METHOD and n.name in ("M", "N")
    ]
    assert {(m.name, m.parent_id) for m in methods} == {
        ("M", defs["I"].id),
        ("N", defs["I"].id),
    }
    _no_calls_edges(out)


def test_go_dot_import_bound() -> None:
    src = 'package main\n\nimport . "example.com/x/utils"\n\nfunc main() {\n\tHelper()\n}\n'
    tree = parse("go", src.encode("utf-8"))
    out = lang_go.collect_go_file("main.go", tree.root_node, "R", 7)
    assert [(i.name, i.module) for i in out.imports] == [
        (".", "example.com/x/utils")
    ]
    assert _buffered_calls(out) == [("main", "Helper", 6)]
    _no_calls_edges(out)


def test_go_method_before_struct_reparents() -> None:
    src = "package p\n\nfunc (s *S) M() {}\n\ntype S struct{}\n"
    tree = parse("go", src.encode("utf-8"))
    out = lang_go.collect_go_file("a.go", tree.root_node, "R", 5)
    defs = _defs_by_name(out)
    assert defs["M"].parent_id == defs["S"].id


def test_go_imported_call_buffered_for_link() -> None:
    src = 'package main\n\nimport h "example.com/x/helper"\n\nfunc main() {\n\th()\n}\n'
    tree = parse("go", src.encode("utf-8"))
    out = lang_go.collect_go_file("main.go", tree.root_node, "R", 7)
    assert _buffered_calls(out) == [("main", "h", 6)]
    _no_calls_edges(out)


def test_go_selector_call_dropped() -> None:
    src = 'package main\n\nimport "fmt"\n\nfunc main() {\n\tfmt.Println("hi")\n}\n'
    tree = parse("go", src.encode("utf-8"))
    out = lang_go.collect_go_file("main.go", tree.root_node, "R", 7)
    assert _buffered_calls(out) == []
    _no_calls_edges(out)
    assert _import_edges(out) == [("fmt", "fmt")]


def test_go_builder_rows() -> None:
    rows = lang_go.build_go_file_rows("R", "a.go", "package p\n\nfunc f() {}\n", {})
    assert rows.language == "go"
    assert [n.name for n in rows.nodes if n.kind == NodeKind.FUNCTION] == ["f"]


def test_python_decorator_bare_buffers_at_line() -> None:
    src = "def retry(fn):\n    return fn\n\n\n@retry\ndef run():\n    pass\n"
    tree = parse("python", src.encode("utf-8"))
    out = lang_python.collect_python_file("a.py", tree.root_node, "R", 7)
    assert _buffered_calls(out) == [("run", "retry", 5)]
    assert "run" in out.definitions
    _no_calls_edges(out)


def test_python_decorator_arg_form_buffers_once() -> None:
    src = (
        "def with_logging(level):\n"
        "    def wrap(fn):\n"
        "        return fn\n"
        "    return wrap\n"
        "\n"
        "\n"
        '@with_logging("debug")\n'
        "def run():\n"
        "    pass\n"
    )
    tree = parse("python", src.encode("utf-8"))
    out = lang_python.collect_python_file("a.py", tree.root_node, "R", 9)
    # Exactly one site: the arg-form call wrapper must not double-count.
    assert _buffered_calls(out) == [("run", "with_logging", 7)]
    _no_calls_edges(out)


def test_python_decorator_stacked_buffers_pair() -> None:
    src = (
        "def a(f):\n"
        "    return f\n"
        "\n"
        "\n"
        "def b(f):\n"
        "    return f\n"
        "\n"
        "\n"
        "@a\n"
        "@b\n"
        "def run():\n"
        "    pass\n"
    )
    tree = parse("python", src.encode("utf-8"))
    out = lang_python.collect_python_file("a.py", tree.root_node, "R", 12)
    assert _buffered_calls(out) == [("run", "a", 9), ("run", "b", 10)]
    _no_calls_edges(out)


def test_python_decorator_class_and_method_targets() -> None:
    src = (
        "def retry(fn):\n"
        "    return fn\n"
        "\n"
        "\n"
        "def register(cls):\n"
        "    return cls\n"
        "\n"
        "\n"
        "@register\n"
        "class Service:\n"
        "    @retry\n"
        "    def call(self):\n"
        "        pass\n"
        "\n"
        "    @property\n"
        "    def status(self):\n"
        "        return 1\n"
    )
    tree = parse("python", src.encode("utf-8"))
    out = lang_python.collect_python_file("a.py", tree.root_node, "R", 17)
    defs = _defs_by_name(out)
    assert defs["Service"].kind == NodeKind.CLASS
    assert defs["call"].kind == NodeKind.METHOD
    # Builtin @property buffers here; the link phase drops it.
    assert _buffered_calls(out) == [
        ("Service", "register", 9),
        ("call", "retry", 11),
        ("status", "property", 15),
    ]
    _no_calls_edges(out)


def test_python_decorator_attribute_skipped() -> None:
    src = '@app.get("/x")\ndef handler():\n    pass\n'
    tree = parse("python", src.encode("utf-8"))
    out = lang_python.collect_python_file("a.py", tree.root_node, "R", 3)
    assert _buffered_calls(out) == []
    assert "handler" in out.definitions
    _no_calls_edges(out)


def test_python_decorator_on_nested_def() -> None:
    src = (
        "def deco(f):\n"
        "    return f\n"
        "\n"
        "\n"
        "def outer():\n"
        "    @deco\n"
        "    def inner():\n"
        "        pass\n"
        "    return inner\n"
    )
    tree = parse("python", src.encode("utf-8"))
    out = lang_python.collect_python_file("a.py", tree.root_node, "R", 9)
    assert _buffered_calls(out) == [("inner", "deco", 6)]
    _no_calls_edges(out)
