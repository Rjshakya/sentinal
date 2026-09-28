"""TypeScript / JavaScript structural extraction from a raw tree.

Collect phase (:func:`collect_ts_file`): walks once, emits defs
(classes, functions, methods, interfaces, type aliases, arrow-bound
consts) + imports with alias originals, and buffers bare-name call
sites unresolved. Call resolution happens later in the link phase
(:mod:`codegraph.parser.links`). Covers both the ``typescript`` and
``javascript`` grammars, which share structure shapes (interfaces and
type aliases only occur in TypeScript).
"""

from __future__ import annotations

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
from codegraph.parser.base import ParsedCall, ParsedDefinition, ParsedImport
from codegraph.parser.raw_core import field_text, node_text, parse, span, walk

TYPESCRIPT: str = "typescript"
JAVASCRIPT: str = "javascript"
LANGUAGE: str = TYPESCRIPT

_MODULE_RE: re.Pattern[str] = re.compile(r"""["']([^"']+)["']""")


def _clause_symbols(clause: str) -> list[tuple[str, str]]:
    """Extract ``(bound, original)`` pairs from the import clause.

    ``{a as b}`` binds ``b`` for the defining-module name ``a``;
    default imports bind with no original (the link phase joins them
    on the bound name); ``* as ns`` binds a namespace (attribute
    calls only, so it never resolves a bare site).
    """
    symbols: list[tuple[str, str]] = []
    text: str = clause.strip()
    if text.startswith("type "):
        text = text[5:].strip()
    if not text:
        return symbols
    if text.startswith("{"):
        inner: str = text[1:]
        if "}" in inner:
            inner = inner[: inner.index("}")]
        for raw in inner.split(","):
            symbol: str = raw.strip()
            if not symbol or symbol.startswith("//"):
                continue
            if symbol.startswith("type "):
                symbol = symbol[5:].strip()
            original, sep, alias = symbol.partition(" as ")
            original = original.strip()
            alias = alias.strip()
            if not original:
                continue
            bound: str = alias if sep and alias else original
            if bound:
                symbols.append((bound, original))
    elif text.startswith("*"):
        _, sep, alias = text.partition(" as ")
        alias = alias.strip()
        symbols.append((alias if sep and alias else "*", ""))
    else:
        head, sep, tail = text.partition(",")
        default: str = head.strip()
        if default and default not in ("*", "{"):
            symbols.append((default, ""))
        if sep and tail.strip():
            symbols.extend(_clause_symbols(tail.strip()))
    return symbols


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
    symbols: list[tuple[str, str]] = _clause_symbols(head) if head else [("*", "")]
    if not symbols:
        symbols = [("*", "")]
    return [
        ParsedImport(
            module=module,
            name=bound,
            start_line=start_line,
            end_line=end_line,
            original="" if bound == original else original,
        )
        for bound, original in symbols
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


@dataclass(slots=True)
class _ActiveDefinition:
    """One live entry on the definition nesting stack."""

    def_kind: str  # "class" | "function"
    def_name: str
    node_id: str
    end_byte: int


@dataclass(slots=True)
class ExtractedFileGraph:
    """Per-file collect output: rows plus unresolved call sites.

    ``definitions`` maps def name -> node id (first registration wins);
    ``imports`` / ``calls`` are the raw IR the link phase resolves.
    No ``calls`` edges are emitted here.
    """

    rel_path: str
    language: str
    total_lines: int
    nodes: dict[str, GraphNode] = dc_field(
        default_factory=lambda: dict[str, GraphNode]()
    )
    edges: list[Edge] = dc_field(default_factory=lambda: list[Edge]())
    definitions: dict[str, str] = dc_field(
        default_factory=lambda: dict[str, str]()
    )
    imports: list[ParsedImport] = dc_field(
        default_factory=lambda: list[ParsedImport]()
    )
    calls: list[ParsedCall] = dc_field(default_factory=lambda: list[ParsedCall]())


def build_defined_node_id(
    rel_path: str, def_name: str, start_line: int, end_line: int
) -> str:
    """Return the symbolic def id ``base:name:start:end``."""
    return f"{rel_path}:{def_name}:{start_line}:{end_line}"


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


def _bare_callee_name(syntax_node: Node) -> str | None:
    """Return the callee name for a bare-name call or construction.

    Covers ``f()`` (``call_expression``) and ``new C()``
    (``new_expression`` — construction is a call). Member calls
    (``obj.m()``) never match by construction.
    """
    if syntax_node.type not in ("call_expression", "new_expression"):
        return None
    function_node: Node | None = syntax_node.child_by_field_name("function")
    if function_node is None:
        function_node = syntax_node.child_by_field_name("constructor")
    if function_node is None or function_node.type != "identifier":
        return None
    return node_text(function_node) or None


def collect_ts_file(
    rel_path: str,
    syntax_root: Node,
    graph_root: str,
    total_lines: int,
) -> ExtractedFileGraph:
    """Walk one TS/JS file once, collecting defs + imports + call sites.

    - defs (classes, functions, methods, interfaces, type aliases,
      arrow-bound consts; ``export`` wrappers are transparent since the
      walk visits nested nodes) → ``Node`` + ``Edge(CONTAINS)`` with
      ``base:name:start:end`` ids.
    - imports → ``Node(IMPORT)`` + ``Edge(IMPORTS)`` (existing
      statement rules, now keeping alias originals).
    - bare calls / constructions with a live enclosing def → buffered
      as ``ParsedCall(caller=name, callee, site_line)`` for the link
      phase. Module-level sites are dropped here.

    Pure given the parsed tree: no module resolution, no ``calls``
    edges.
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

    for syntax_node in walk(syntax_root):
        if syntax_node.type in (
            "class_declaration",
            "function_declaration",
            "method_definition",
            "method_signature",
            "interface_declaration",
            "type_alias_declaration",
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
            elif syntax_node.type == "interface_declaration":
                def_name = field_text(syntax_node, "name")
                graph_node_kind = NodeKind.INTERFACE
                stack_kind = "class"
            elif syntax_node.type == "type_alias_declaration":
                def_name = field_text(syntax_node, "name")
                graph_node_kind = NodeKind.TYPE
                stack_kind = "function"
            elif syntax_node.type == "method_signature":
                def_name = field_text(syntax_node, "name")
                graph_node_kind = NodeKind.METHOD
                stack_kind = "function"
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
                extracted_file.imports.append(parsed_import)
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
            extracted_file.calls.append(
                ParsedCall(
                    caller=active_definition_stack[-1].def_name,
                    callee=callee_name,
                    site_line=call_site_line,
                )
            )

    extracted_file.definitions.update(first_def_node_id_by_name)
    return extracted_file


def build_ts_file_rows(
    root: str,
    rel_path: str,
    source_text: str,
    _import_index: Mapping[str, str],
) -> FileRows:
    """Build one TS/JS file's rows via the collect phase.

    Nodes + ``contains`` / ``imports`` edges come out of
    :func:`collect_ts_file` directly; ``calls`` edges are never
    emitted here — ``rows.calls`` carries the buffered call sites for
    :func:`codegraph.parser.links.resolve_call_edges`.
    ``_import_index`` is accepted for builder-signature uniformity and
    ignored: the link phase resolves modules from the full file set.
    """
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
    out: ExtractedFileGraph = collect_ts_file(
        rel_path, tree.root_node, root, total_lines
    )
    rows.nodes.extend(out.nodes.values())
    rows.edges.extend(out.edges)
    rows.definitions.update(out.definitions)
    for parsed_import in out.imports:
        rows.imports.setdefault(parsed_import.name, parsed_import.module)
    rows.import_details.extend(out.imports)
    rows.calls.extend(out.calls)
    return rows


__all__ = [
    "ExtractedFileGraph",
    "JAVASCRIPT",
    "LANGUAGE",
    "TYPESCRIPT",
    "build_defined_node_id",
    "build_ts_file_rows",
    "collect_ts_file",
    "extract_definitions",
    "extract_imports",
]
