"""TypeScript / JavaScript structural extraction from a raw tree.

Pure: takes the parsed ``root``, returns defs + imports. Covers both the
``typescript`` and ``javascript`` grammars, which share structure shapes.
"""

from __future__ import annotations

import posixpath
import re
from collections.abc import Mapping
from dataclasses import dataclass
from dataclasses import field as dc_field
from pathlib import Path
from typing import TYPE_CHECKING

from tree_sitter import Node

if TYPE_CHECKING:
    from codegraph.parser.rows import FileRows

from codegraph.models import Edge, EdgeKind
from codegraph.models import Node as GraphNode
from codegraph.models import NodeKind
from codegraph.parser.base import ParsedDefinition, ParsedImport
from codegraph.parser.raw_core import field_text, node_text, parse, span, walk

TYPESCRIPT: str = "typescript"
JAVASCRIPT: str = "javascript"
LANGUAGE: str = TYPESCRIPT

_MODULE_RE: re.Pattern[str] = re.compile(r"""["']([^"']+)["']""")


def _clause_names(clause: str) -> list[str]:
    """Extract bound names from the ``import …`` clause (pre-``from``)."""
    names: list[str] = []
    text: str = clause.strip()
    if text.startswith("type "):
        text = text[5:].strip()
    if not text:
        return names
    if text.startswith("{"):
        inner: str = text[1:]
        if "}" in inner:
            inner = inner[: inner.index("}")]
        for raw in inner.split(","):
            symbol: str = raw.strip()
            if not symbol or symbol.startswith("//"):
                continue
            _, sep, alias = symbol.partition(" as ")
            names.append(alias.strip() if sep else symbol)
    elif text.startswith("*"):
        _, sep, alias = text.partition(" as ")
        names.append(alias.strip() if sep else "*")
    else:
        head, sep, tail = text.partition(",")
        default: str = head.strip()
        if default and default not in ("*", "{"):
            names.append(default)
        if sep and tail.strip():
            names.extend(_clause_names(tail.strip()))
    return [name for name in names if name]


def _imports_from_statement(
    source: str, start_line: int, end_line: int
) -> list[ParsedImport]:
    """Parse one TS/JS import statement into per-name import rows."""
    match: re.Match[str] | None = _MODULE_RE.search(source)
    if match is None:
        return []
    module: str = match.group(1).strip()
    if not module:
        return []
    head: str = source[: match.start()].strip()
    if head.startswith("import"):
        head = head[6:].strip()
    else:
        return []
    head = re.sub(r"\bfrom\s*$", "", head).strip()
    names: list[str] = _clause_names(head) if head else ["*"]
    if not names:
        names = ["*"]
    return [
        ParsedImport(module=module, name=name, start_line=start_line, end_line=end_line)
        for name in names
    ]


def extract_imports(root: Node) -> list[ParsedImport]:
    """Collect imports from ``import_statement`` nodes."""
    found: list[ParsedImport] = []
    for node in walk(root):
        if node.type != "import_statement":
            continue
        text: str = node_text(node)
        if not text.strip().startswith("import"):
            continue
        start, end = span(node)
        found.extend(_imports_from_statement(text, start, end))
    return found


def _bound_variable_name(node: Node) -> str:
    """Return the variable name binding an arrow/function expression."""
    parent: Node | None = node.parent
    if parent is not None and parent.type == "variable_declarator":
        return field_text(parent, "name")
    return ""


def extract_definitions(root: Node) -> list[ParsedDefinition]:
    """Collect classes, functions, methods, and arrow-bound consts (preorder)."""
    found: list[ParsedDefinition] = []
    scope: list[tuple[str, str]] = []  # enclosing (kind, name)
    stack: list[tuple[Node, bool]] = [(root, False)]  # True = exit, pops scope
    while stack:
        node, exiting = stack.pop()
        if exiting:
            scope.pop()
            continue
        if node.type == "class_declaration":
            kind: str = "class"
            name: str = field_text(node, "name")
        elif node.type == "function_declaration":
            kind = "method" if scope and scope[-1][0] == "class" else "function"
            name = field_text(node, "name")
        elif node.type == "method_definition":
            kind = "method"
            name = field_text(node, "name")
        elif node.type in ("arrow_function", "function_expression"):
            kind = "function"
            name = _bound_variable_name(node)
        else:
            for child in reversed(node.named_children):
                stack.append((child, False))
            continue
        if not name:
            for child in reversed(node.named_children):
                stack.append((child, False))
            continue
        start, end = span(node)
        found.append(
            ParsedDefinition(
                kind=kind,
                name=name,
                start_line=start,
                end_line=end,
                parent=scope[-1][1] if scope else None,
            )
        )
        scope.append(("class" if kind == "class" else "function", name))
        stack.append((node, True))
        for child in reversed(node.named_children):
            stack.append((child, False))
    return found


_TS_EXTENSIONS: tuple[str, ...] = (".ts", ".tsx", ".js", ".jsx")


@dataclass(slots=True)
class _ActiveDefinition:
    """One live entry on the definition nesting stack."""

    def_kind: str  # "class" | "function"
    def_name: str
    node_id: str
    end_byte: int


@dataclass(slots=True)
class ExtractedFileGraph:
    """Per-file emitter output: storage rows, ready to merge."""

    rel_path: str
    language: str
    total_lines: int
    nodes: dict[str, GraphNode] = dc_field(
        default_factory=lambda: dict[str, GraphNode]()
    )
    edges: list[Edge] = dc_field(default_factory=lambda: list[Edge]())


def build_defined_node_id(
    rel_path: str, def_name: str, start_line: int, end_line: int
) -> str:
    """Return the symbolic def id ``base:name:start:end``."""
    return f"{rel_path}:{def_name}:{start_line}:{end_line}"


def build_assumed_callee_id(resolved_callee_rel_path: str, callee_name: str) -> str:
    """Return the assumed callee id ``base:name`` (lines unknowable per file)."""
    return f"{resolved_callee_rel_path}:{callee_name}"


def _pop_finished_definitions(
    active_definition_stack: list[_ActiveDefinition], byte_offset: int
) -> None:
    """Pop stack tops whose def ended before byte offset ``byte_offset``."""
    while active_definition_stack and byte_offset > active_definition_stack[-1].end_byte:
        active_definition_stack.pop()


def _register_node_once(
    nodes_by_id: dict[str, GraphNode],
    *,
    node_id: str,
    graph_root: str,
    rel_path: str,
    language: str,
    kind: NodeKind,
    name: str,
    start_line: int,
    end_line: int,
    parent_id: str | None,
) -> None:
    """Insert a node row (first registration wins)."""
    if node_id in nodes_by_id:
        return
    nodes_by_id[node_id] = GraphNode(
        id=node_id,
        root=graph_root,
        file_path=rel_path,
        kind=kind,
        name=name,
        language=language,
        start_line=start_line,
        end_line=end_line,
        parent_id=parent_id,
    )


def _register_edge_once(
    emitted_edges: list[Edge],
    emitted_edge_keys: set[tuple[str, str, str]],
    *,
    graph_root: str,
    src_id: str,
    dst_id: str,
    kind: EdgeKind,
    target_module: str | None = None,
    site_line: int | None = None,
) -> None:
    """Append an edge row, deduped by ``(src, dst, kind)``."""
    key: tuple[str, str, str] = (src_id, dst_id, kind.value)
    if key in emitted_edge_keys:
        return
    emitted_edge_keys.add(key)
    emitted_edges.append(
        Edge(
            id=f"{src_id}::{kind.value}::{dst_id}",
            root=graph_root,
            src_id=src_id,
            dst_id=dst_id,
            kind=kind,
            target_module=target_module,
            site_line=site_line,
        )
    )


def _ts_lookup_keys(module_specifier: str, importer_rel_path: str) -> list[str]:
    """Return candidate rel paths for a relative TS/JS module specifier."""
    if not module_specifier.startswith("."):
        return []
    base: str = posixpath.normpath(
        posixpath.join(posixpath.dirname(importer_rel_path), module_specifier)
    )
    keys: list[str] = [base]
    keys.extend(base + ext for ext in _TS_EXTENSIONS)
    keys.extend(base + "/index" + ext for ext in _TS_EXTENSIONS)
    return keys


def _bare_callee_name(syntax_node: Node) -> str | None:
    """Return the callee name for a bare-name call, else None."""
    if syntax_node.type != "call_expression":
        return None
    function_node: Node | None = syntax_node.child_by_field_name("function")
    if function_node is None or function_node.type != "identifier":
        return None
    return node_text(function_node) or None


def extract_nodes_and_edges(
    rel_path: str,
    syntax_root: Node,
    graph_root: str,
    total_lines: int,
    import_index: Mapping[str, str],
) -> ExtractedFileGraph:
    """Walk one TS/JS file once, emitting nodes + edges inline.

    - defs → ``Node`` + ``Edge(CONTAINS)`` with ``base:name:start:end`` ids.
    - imports → ``Node(IMPORT)`` + ``Edge(IMPORTS)`` (existing statement rules).
    - bare calls with a live enclosing def → same-file hit by name, else
      assumed ``base:name`` edge via ``import_index`` (relative specifiers
      only); natives (no def, no import) are dropped and stored nowhere.
    """
    suffix: str = Path(rel_path).suffix.lower()
    language: str = JAVASCRIPT if suffix in (".js", ".jsx") else TYPESCRIPT
    extracted_file = ExtractedFileGraph(
        rel_path=rel_path, language=language, total_lines=total_lines
    )
    _register_node_once(
        extracted_file.nodes,
        node_id=rel_path,
        graph_root=graph_root,
        rel_path=rel_path,
        language=language,
        kind=NodeKind.FILE,
        name=Path(rel_path).name,
        start_line=1,
        end_line=total_lines,
        parent_id=None,
    )
    active_definition_stack: list[_ActiveDefinition] = []
    emitted_edge_keys: set[tuple[str, str, str]] = set()
    first_def_node_id_by_name: dict[str, str] = {}
    module_specifier_by_bound_name: dict[str, str] = {}
    deferred_call_sites: list[tuple[str, str, int]] = []

    for syntax_node in walk(syntax_root):
        if syntax_node.type in (
            "class_declaration",
            "function_declaration",
            "method_definition",
            "arrow_function",
            "function_expression",
        ):
            _pop_finished_definitions(
                active_definition_stack, syntax_node.start_byte
            )
            if syntax_node.type == "class_declaration":
                def_name: str = field_text(syntax_node, "name")
                graph_node_kind: NodeKind = NodeKind.CLASS
                stack_kind: str = "class"
            elif syntax_node.type == "function_declaration":
                def_name = field_text(syntax_node, "name")
                is_method: bool = bool(
                    active_definition_stack
                    and active_definition_stack[-1].def_kind == "class"
                )
                graph_node_kind = NodeKind.METHOD if is_method else NodeKind.FUNCTION
                stack_kind = "function"
            elif syntax_node.type == "method_definition":
                def_name = field_text(syntax_node, "name")
                graph_node_kind = NodeKind.METHOD
                stack_kind = "function"
            else:
                def_name = _bound_variable_name(syntax_node)
                graph_node_kind = NodeKind.FUNCTION
                stack_kind = "function"
            if not def_name:
                continue
            start_line, end_line = span(syntax_node)
            definition_node_id: str = build_defined_node_id(
                rel_path, def_name, start_line, end_line
            )
            parent_node_id: str = (
                active_definition_stack[-1].node_id
                if active_definition_stack
                else rel_path
            )
            _register_node_once(
                extracted_file.nodes,
                node_id=definition_node_id,
                graph_root=graph_root,
                rel_path=rel_path,
                language=language,
                kind=graph_node_kind,
                name=def_name,
                start_line=start_line,
                end_line=end_line,
                parent_id=parent_node_id,
            )
            _register_edge_once(
                extracted_file.edges,
                emitted_edge_keys,
                graph_root=graph_root,
                src_id=parent_node_id,
                dst_id=definition_node_id,
                kind=EdgeKind.CONTAINS,
            )
            first_def_node_id_by_name.setdefault(def_name, definition_node_id)
            active_definition_stack.append(
                _ActiveDefinition(
                    def_kind=stack_kind,
                    def_name=def_name,
                    node_id=definition_node_id,
                    end_byte=syntax_node.end_byte,
                )
            )
        elif syntax_node.type == "import_statement":
            import_statement_text: str = node_text(syntax_node)
            if not import_statement_text.strip().startswith("import"):
                continue
            start_line, end_line = span(syntax_node)
            for parsed_import in _imports_from_statement(
                import_statement_text, start_line, end_line
            ):
                import_node_id: str = (
                    f"{rel_path}:import:{parsed_import.name}:{start_line}"
                )
                _register_node_once(
                    extracted_file.nodes,
                    node_id=import_node_id,
                    graph_root=graph_root,
                    rel_path=rel_path,
                    language=language,
                    kind=NodeKind.IMPORT,
                    name=parsed_import.name,
                    start_line=start_line,
                    end_line=end_line,
                    parent_id=rel_path,
                )
                _register_edge_once(
                    extracted_file.edges,
                    emitted_edge_keys,
                    graph_root=graph_root,
                    src_id=rel_path,
                    dst_id=import_node_id,
                    kind=EdgeKind.IMPORTS,
                    target_module=parsed_import.module,
                )
                module_specifier_by_bound_name.setdefault(
                    parsed_import.name, parsed_import.module
                )
        else:
            callee_name: str | None = _bare_callee_name(syntax_node)
            if callee_name is None:
                continue
            _pop_finished_definitions(
                active_definition_stack, syntax_node.start_byte
            )
            if not active_definition_stack:
                continue  # module-level call: drop
            call_site_line: int = span(syntax_node)[0]
            deferred_call_sites.append(
                (active_definition_stack[-1].node_id, callee_name, call_site_line)
            )

    for caller_node_id, callee_name, call_site_line in deferred_call_sites:
        same_file_callee_id: str | None = first_def_node_id_by_name.get(callee_name)
        if same_file_callee_id is not None:
            _register_edge_once(
                extracted_file.edges,
                emitted_edge_keys,
                graph_root=graph_root,
                src_id=caller_node_id,
                dst_id=same_file_callee_id,
                kind=EdgeKind.CALLS,
                site_line=call_site_line,
            )
            continue
        imported_module_specifier: str | None = module_specifier_by_bound_name.get(
            callee_name
        )
        if imported_module_specifier is None:
            continue  # native / builtin / unknown: store nothing
        resolved_callee_rel_path: str | None = None
        for module_lookup_key in _ts_lookup_keys(
            imported_module_specifier, rel_path
        ):
            indexed_rel_path: str | None = import_index.get(module_lookup_key)
            if indexed_rel_path is not None:
                resolved_callee_rel_path = indexed_rel_path
                break
        if resolved_callee_rel_path is None:
            continue  # npm / stdlib / unindexed: drop
        _register_edge_once(
            extracted_file.edges,
            emitted_edge_keys,
            graph_root=graph_root,
            src_id=caller_node_id,
            dst_id=build_assumed_callee_id(resolved_callee_rel_path, callee_name),
            kind=EdgeKind.CALLS,
            site_line=call_site_line,
        )
    return extracted_file


def build_ts_file_rows(
    root: str,
    rel_path: str,
    source_text: str,
    import_index: Mapping[str, str],
) -> FileRows:
    """Build one TS/JS file's rows (same contract as ``build_python_file_rows``)."""
    from codegraph.parser.rows import FileRows

    suffix: str = Path(rel_path).suffix.lower()
    language: str = JAVASCRIPT if suffix in (".js", ".jsx") else TYPESCRIPT
    total_lines: int = max(source_text.count("\n") + 1, 1)
    rows = FileRows(rel_path=rel_path, language=language)
    if not source_text.strip():
        rows.nodes.append(
            GraphNode(
                id=rel_path,
                root=root,
                file_path=rel_path,
                kind=NodeKind.FILE,
                name=Path(rel_path).name,
                language=language,
                start_line=1,
                end_line=total_lines,
                parent_id=None,
            )
        )
        return rows
    grammar: str = language
    tree = parse(grammar, source_text.encode("utf-8"))
    out: ExtractedFileGraph = extract_nodes_and_edges(
        rel_path, tree.root_node, root, total_lines, import_index
    )
    rows.nodes.extend(out.nodes.values())
    rows.edges.extend(out.edges)
    return rows


__all__ = [
    "ExtractedFileGraph",
    "JAVASCRIPT",
    "LANGUAGE",
    "TYPESCRIPT",
    "build_assumed_callee_id",
    "build_defined_node_id",
    "build_ts_file_rows",
    "extract_definitions",
    "extract_imports",
    "extract_nodes_and_edges",
]
