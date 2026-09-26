"""Python structural extraction from a raw tree-sitter tree.

Collect phase (:func:`collect_python_file`): walks once with a single
``active_definition_stack`` (byte-offset expiry), emits nodes +
``contains`` / ``imports`` edges inline with ``base:name:start:end``
ids, and buffers bare-name call sites unresolved. Call resolution
happens later in the link phase (:mod:`codegraph.parser.links`)
against the global definition registry + per-file import map, so this
module never resolves modules and never emits ``calls`` edges.
Decorator call sites are buffered per decorated definition and drained
into the next ``function_definition`` / ``class_definition`` node as
``ParsedCall`` rows carrying the @-line; the link phase resolves them
like any other call (attribute decorators are skipped, builtins drop).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from tree_sitter import Node

from codegraph.models import Edge, EdgeKind, Node as GraphNode, NodeKind
from codegraph.parser.base import ParsedCall, ParsedImport
from codegraph.parser.raw_core import field_text, node_text, span, walk

LANGUAGE: str = "python"

DefinitionKind = Literal["class", "function"]


def _definition_name(syntax_node: Node) -> str:
    return field_text(syntax_node, "name")


def _bare_callee_name(syntax_node: Node) -> str | None:
    """Return the callee name for a bare-name call, else None."""
    if syntax_node.type != "call":
        return None
    function_node: Node | None = syntax_node.child_by_field_name("function")
    if function_node is None or function_node.type != "identifier":
        return None
    return node_text(function_node) or None


def _decorator_callee_name(syntax_node: Node) -> str | None:
    """Return the decorator callee for a ``decorator`` node, else None.

    Bare ``@retry`` unwraps the single ``identifier`` child; arg-form
    ``@with_logging("debug")`` unwraps one ``call`` layer via its
    ``function`` field. Attribute decorators (``@app.get``) return None
    (skipped, per the no-attribute rule).
    """
    if syntax_node.type != "decorator":
        return None
    callee_nodes: list[Node] = syntax_node.named_children
    if len(callee_nodes) != 1:
        return None
    callee_node: Node = callee_nodes[0]
    if callee_node.type == "identifier":
        return node_text(callee_node) or None
    if callee_node.type == "call":
        return _bare_callee_name(callee_node)
    return None


@dataclass(slots=True)
class _ActiveDefinition:
    """One live entry on the definition nesting stack: enclosing class or function."""

    def_kind: DefinitionKind  # "class" | "function"
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
    nodes: dict[str, GraphNode] = field(
        default_factory=lambda: dict[str, GraphNode]()
    )
    edges: list[Edge] = field(default_factory=lambda: list[Edge]())
    definitions: dict[str, str] = field(
        default_factory=lambda: dict[str, str]()
    )
    imports: list[ParsedImport] = field(
        default_factory=lambda: list[ParsedImport]()
    )
    calls: list[ParsedCall] = field(default_factory=lambda: list[ParsedCall]())


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


def _find_innermost_definition_of_kind(
    active_definition_stack: list[_ActiveDefinition], def_kind: DefinitionKind
) -> _ActiveDefinition | None:
    """Return the innermost live stack entry of ``def_kind``."""
    for active_definition in reversed(active_definition_stack):
        if active_definition.def_kind == def_kind:
            return active_definition
    return None


def _imports_from_statement(
    source: str, start_line: int, end_line: int
) -> list[ParsedImport]:
    """Parse one Python import statement into per-name import rows.

    ``from`` imports keep both the bound name and the defining-module
    name (``from utils import helper as h`` -> bound ``h``,
    original ``helper``); the link phase joins on the original.
    """
    parsed_imports: list[ParsedImport] = []
    text: str = " ".join(source.replace("(", " ").replace(")", " ").split())
    if text.startswith("from "):
        rest: str = text[5:]
        module, sep, names_part = rest.partition(" import ")
        module = module.strip()
        if not sep or not module:
            return parsed_imports
        for raw in names_part.split(","):
            symbol: str = raw.strip().rstrip(";")
            if not symbol:
                continue
            if symbol == "*":
                parsed_imports.append(
                    ParsedImport(
                        module=module,
                        name="*",
                        start_line=start_line,
                        end_line=end_line,
                        original="*",
                    )
                )
                continue
            original, alias_sep, alias = symbol.partition(" as ")
            original = original.strip()
            alias = alias.strip()
            if not original:
                continue
            bound_name: str = alias if alias_sep else original
            if not bound_name:
                continue
            parsed_imports.append(
                ParsedImport(
                    module=module,
                    name=bound_name,
                    start_line=start_line,
                    end_line=end_line,
                    original="" if bound_name == original else original,
                )
            )
    elif text.startswith("import "):
        rest = text[7:]
        for raw in rest.split(","):
            symbol = raw.strip().rstrip(";")
            if not symbol:
                continue
            dotted, sep, alias = symbol.partition(" as ")
            dotted = dotted.strip()
            if not dotted:
                continue
            bound_name = alias.strip() if sep else dotted.split(".")[0]
            if bound_name:
                parsed_imports.append(
                    ParsedImport(
                        module=dotted,
                        name=bound_name,
                        start_line=start_line,
                        end_line=end_line,
                    )
                )
    return parsed_imports


_IMPORT_RE: re.Pattern[str] = re.compile(r"^\s*(import\s+|from\s+)")


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


def collect_python_file(
    rel_path: str,
    syntax_root: Node,
    graph_root: str,
    total_lines: int,
) -> ExtractedFileGraph:
    """Walk one Python file once, collecting defs + imports + call sites.

    - defs → ``Node`` + ``Edge(CONTAINS)`` with ``base:name:start:end`` ids.
    - imports → ``Node(IMPORT)`` + ``Edge(IMPORTS)`` (existing statement rules).
    - bare calls with a live enclosing def → buffered as
      ``ParsedCall(caller=name, callee, site_line)`` for the link phase.
      Module-level call sites are dropped here.

    Pure given the parsed tree: no module resolution, no ``calls`` edges.
    """
    language: str = LANGUAGE
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
    # Single unified LIFO stack preserving nesting order (class + function
    # entries interleaved). Separate class/function stacks would lose the
    # parent chain for closures (def-in-method-in-class) and double the
    # byte-offset prune logic, so one stack is kept and named as such.
    active_definition_stack: list[_ActiveDefinition] = []
    # Decorator call sites buffered here and drained into the next
    # def/class node: (callee_name, at_line). A skipped attribute
    # decorator buffers nothing, so the drain always pairs exactly
    # with the wrapped definition.
    pending_decorator_sites: list[tuple[str, int]] = []
    emitted_edge_keys: set[tuple[str, str, str]] = set()
    first_def_node_id_by_name: dict[str, str] = {}

    for syntax_node in walk(syntax_root):
        if syntax_node.type == "decorator":
            decorator_callee: str | None = _decorator_callee_name(syntax_node)
            if decorator_callee is not None:
                decorator_line: int = span(syntax_node)[0]  # the @-line
                pending_decorator_sites.append((decorator_callee, decorator_line))
            continue
        if syntax_node.type in ("class_definition", "function_definition"):
            _pop_finished_definitions(
                active_definition_stack, syntax_node.start_byte
            )
            def_name: str = _definition_name(syntax_node)
            if not def_name:
                continue
            for decorator_callee, decorator_line in pending_decorator_sites:
                extracted_file.calls.append(
                    ParsedCall(
                        caller=def_name,
                        callee=decorator_callee,
                        site_line=decorator_line,
                    )
                )
            pending_decorator_sites.clear()
            if syntax_node.type == "class_definition":
                definition_kind_label: str = "class"
                graph_node_kind: NodeKind = NodeKind.CLASS
                enclosing_definition: _ActiveDefinition | None = (
                    active_definition_stack[-1] if active_definition_stack else None
                )
            else:
                enclosing_class_definition: _ActiveDefinition | None = (
                    _find_innermost_definition_of_kind(active_definition_stack, "class")
                )
                is_direct_method_of_class: bool = (
                    enclosing_class_definition is not None
                    and bool(active_definition_stack)
                    and active_definition_stack[-1] is enclosing_class_definition
                )
                definition_kind_label = (
                    "method" if is_direct_method_of_class else "function"
                )
                graph_node_kind = (
                    NodeKind.METHOD if is_direct_method_of_class else NodeKind.FUNCTION
                )
                enclosing_definition = (
                    active_definition_stack[-1] if active_definition_stack else None
                )
            start_line, end_line = span(syntax_node)
            definition_node_id: str = build_defined_node_id(
                rel_path, def_name, start_line, end_line
            )
            parent_node_id: str = (
                enclosing_definition.node_id
                if enclosing_definition is not None
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
                    def_kind="class" if definition_kind_label == "class" else "function",
                    def_name=def_name,
                    node_id=definition_node_id,
                    end_byte=syntax_node.end_byte,
                )
            )
        elif syntax_node.type in ("import_statement", "import_from_statement"):
            import_statement_text: str = node_text(syntax_node)
            if not _IMPORT_RE.match(import_statement_text):
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
            if syntax_node.type == "call" and (
                syntax_node.parent is not None
                and syntax_node.parent.type == "decorator"
            ):
                continue  # arg-form wrapper (e.g. with_logging("debug")):
                # already buffered by the decorator branch above
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


__all__ = [
    "ExtractedFileGraph",
    "LANGUAGE",
    "build_defined_node_id",
    "collect_python_file",
]
