"""Emitter unit tests: TS/JS + Go single-pass extraction.

Each language implements
``extract_nodes_and_edges(rel_path, root, graph_root, total_lines,
import_index)``; these tests pin the shared contract (node id shapes,
same-file-first call resolution, assumed ``base:name`` refs, native /
module-level / attribute drops) plus each grammar's own defs, imports,
and module lookup.
"""

from __future__ import annotations

from typing import Any

from codegraph.models import EdgeKind, Node, NodeKind
from codegraph.parser import lang_go, lang_python, lang_typescript
from codegraph.parser.links import build_import_index
from codegraph.parser.raw_core import parse


def _defs_by_name(out: Any) -> dict[str, Node]:
    found: dict[str, Node] = {}
    for node in out.nodes.values():
        if node.kind in (NodeKind.CLASS, NodeKind.METHOD, NodeKind.FUNCTION):
            found.setdefault(node.name, node)
    return found


def _calls_by_name(out: Any) -> list[tuple[str, str, int | None]]:
    by_id: dict[str, Node] = out.nodes
    calls: list[tuple[str, str, int | None]] = []
    for edge in out.edges:
        if edge.kind != EdgeKind.CALLS:
            continue
        calls.append((by_id[edge.src_id].name, edge.dst_id, edge.site_line))
    return calls


def _import_edges(out: Any) -> list[tuple[str, str | None]]:
    by_id: dict[str, Node] = out.nodes
    return [
        (by_id[edge.dst_id].name, edge.target_module)
        for edge in out.edges
        if edge.kind == EdgeKind.IMPORTS
    ]


def test_python_id_shapes() -> None:
    assert lang_python.build_defined_node_id("a.py", "f", 1, 2) == "a.py:f:1:2"
    assert lang_python.build_assumed_callee_id("u.py", "h") == "u.py:h"


def test_typescript_defs_imports_calls() -> None:
    src = (
        'import x from "mod";\n'
        'import {a, b as c} from "m2";\n'
        "export class C { m() { helper(); } }\n"
        "export function f() { g(); }\n"
        "const g = () => { f(); };\n"
    )
    tree = parse("typescript", src.encode("utf-8"))
    out = lang_typescript.extract_nodes_and_edges(
        "a.ts", tree.root_node, "R", 6, build_import_index(["a.ts"])
    )
    defs = _defs_by_name(out)
    assert (defs["C"].kind, defs["m"].kind) == (NodeKind.CLASS, NodeKind.METHOD)
    assert (defs["f"].kind, defs["g"].kind) == (
        NodeKind.FUNCTION,
        NodeKind.FUNCTION,
    )
    assert defs["m"].parent_id == defs["C"].id
    assert sorted(_import_edges(out)) == [("a", "m2"), ("c", "m2"), ("x", "mod")]
    calls = {(caller, dst) for caller, dst, _ in _calls_by_name(out)}
    assert calls == {("f", "a.ts:g:5:5"), ("g", "a.ts:f:4:4")}
    sites = {(caller, site) for caller, _, site in _calls_by_name(out)}
    assert sites == {("f", 4), ("g", 5)}


def test_typescript_assumed_cross_file_call() -> None:
    src = 'import { helper } from "./helper";\nexport function run() { helper(); }\n'
    tree = parse("typescript", src.encode("utf-8"))
    index = build_import_index(["a.ts", "helper.ts"])
    out = lang_typescript.extract_nodes_and_edges(
        "a.ts", tree.root_node, "R", 2, index
    )
    calls = _calls_by_name(out)
    assert [(caller, dst) for caller, dst, _ in calls] == [
        ("run", "helper.ts:helper")
    ]


def test_typescript_bare_specifier_call_dropped() -> None:
    src = 'import x from "mod";\nexport function f() { x(); }\n'
    tree = parse("typescript", src.encode("utf-8"))
    out = lang_typescript.extract_nodes_and_edges(
        "a.ts", tree.root_node, "R", 2, build_import_index(["a.ts"])
    )
    assert [e for e in out.edges if e.kind == EdgeKind.CALLS] == []
    assert _import_edges(out) == [("x", "mod")]


def test_typescript_module_level_and_attribute_calls_dropped() -> None:
    src = 'import o from "./o";\no.method();\nbare();\n'
    tree = parse("typescript", src.encode("utf-8"))
    out = lang_typescript.extract_nodes_and_edges(
        "a.ts", tree.root_node, "R", 3, build_import_index(["a.ts", "o.ts"])
    )
    assert [e for e in out.edges if e.kind == EdgeKind.CALLS] == []


def test_typescript_side_effect_import() -> None:
    tree = parse("typescript", b'import "./polyfill";\n')
    out = lang_typescript.extract_nodes_and_edges(
        "a.ts", tree.root_node, "R", 1, build_import_index(["a.ts"])
    )
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
    out = lang_go.extract_nodes_and_edges(
        "a.go", tree.root_node, "R", 17, build_import_index(["a.go"])
    )
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
    calls = _calls_by_name(out)
    assert len(calls) == 1
    caller, dst, site = calls[0]
    assert (caller, dst, site) == ("M", "a.go:Helper:9:9", 16)


def test_go_interface_ignored() -> None:
    src = "package p\n\ntype I interface {\n\tM()\n}\n\ntype S struct{}\n"
    tree = parse("go", src.encode("utf-8"))
    out = lang_go.extract_nodes_and_edges(
        "a.go", tree.root_node, "R", 7, build_import_index(["a.go"])
    )
    assert sorted(_defs_by_name(out)) == ["S"]


def test_go_method_before_struct_reparents() -> None:
    src = "package p\n\nfunc (s *S) M() {}\n\ntype S struct{}\n"
    tree = parse("go", src.encode("utf-8"))
    out = lang_go.extract_nodes_and_edges(
        "a.go", tree.root_node, "R", 5, build_import_index(["a.go"])
    )
    defs = _defs_by_name(out)
    assert defs["M"].parent_id == defs["S"].id


def test_go_assumed_cross_file_call_via_tail() -> None:
    src = 'package main\n\nimport h "example.com/x/helper"\n\nfunc main() {\n\th()\n}\n'
    tree = parse("go", src.encode("utf-8"))
    index = build_import_index(["main.go", "lib/helper.go"])
    out = lang_go.extract_nodes_and_edges(
        "main.go", tree.root_node, "R", 7, index
    )
    calls = _calls_by_name(out)
    assert [(caller, dst) for caller, dst, _ in calls] == [
        ("main", "lib/helper.go:h")
    ]


def test_go_selector_call_dropped() -> None:
    src = 'package main\n\nimport "fmt"\n\nfunc main() {\n\tfmt.Println("hi")\n}\n'
    tree = parse("go", src.encode("utf-8"))
    out = lang_go.extract_nodes_and_edges(
        "main.go", tree.root_node, "R", 7, build_import_index(["main.go"])
    )
    assert [e for e in out.edges if e.kind == EdgeKind.CALLS] == []
    assert _import_edges(out) == [("fmt", "fmt")]


def test_go_builder_rows() -> None:
    rows = lang_go.build_go_file_rows("R", "a.go", "package p\n\nfunc f() {}\n", {})
    assert rows.language == "go"
    assert [n.name for n in rows.nodes if n.kind == NodeKind.FUNCTION] == ["f"]
