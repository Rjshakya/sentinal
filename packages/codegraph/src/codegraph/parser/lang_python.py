"""Python structural extraction from a raw tree-sitter tree.

Single-pass v2 emitter (:func:`extract_nodes_and_edges`): walks once with a single
``active_definition_stack`` (byte-offset expiry), emits nodes + edges
inline with ``base:name:start:end`` ids, and resolves calls in a
same-function flush: same-file hits by name, imported callees as
assumed ``base:name`` edges via the frozen import index, natives
dropped. Decorated definitions are transparent — the inner
``function_definition`` / ``class_definition`` owns the name and span.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from tree_sitter import Node

from codegraph.models import Edge, EdgeKind, Node as GraphNode, NodeKind
from codegraph.parser.base import ParsedImport
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


@dataclass(slots=True)
class _ActiveDefinition:
    """One live entry on the definition nesting stack: enclosing class or function."""

    def_kind: DefinitionKind  # "class" | "function"
    def_name: str
    node_id: str
    end_byte: int


@dataclass(slots=True)
class ExtractedFileGraph:
    """Per-file emitter output: storage rows, ready to merge."""

    rel_path: str
    language: str
    total_lines: int
    nodes: dict[str, GraphNode] = field(
        default_factory=lambda: dict[str, GraphNode]()
    )
    edges: list[Edge] = field(default_factory=lambda: list[Edge]())


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


def _find_innermost_definition_of_kind(
    active_definition_stack: list[_ActiveDefinition], def_kind: DefinitionKind
) -> _ActiveDefinition | None:
    """Return the innermost live stack entry of ``def_kind``."""
    for active_definition in reversed(active_definition_stack):
        if active_definition.def_kind == def_kind:
            return active_definition
    return None


def _split_alias(symbol: str) -> str:
    _, sep, alias = symbol.partition(" as ")
    return alias.strip() if sep else symbol.strip()


def _imports_from_statement(
    source: str, start_line: int, end_line: int
) -> list[ParsedImport]:
    """Parse one Python import statement into per-name import rows."""
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
                        module=module, name="*", start_line=start_line, end_line=end_line
                    )
                )
            else:
                bound_name: str = _split_alias(symbol)
                if bound_name:
                    parsed_imports.append(
                        ParsedImport(
                            module=module,
                            name=bound_name,
                            start_line=start_line,
                            end_line=end_line,
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


def _module_index_lookup_keys(
    module_specifier: str, importer_rel_path: str
) -> list[str]:
    """Return absolute dotted module keys to try, longest-first.

    Pure string ops over the importer's path — no filesystem, no index.
    """
    if module_specifier.startswith("."):
        level: int = len(module_specifier) - len(module_specifier.lstrip("."))
        rest: str = module_specifier.lstrip(".")
        importer_package_parts: list[str] = importer_rel_path.split("/")[
            :-1
        ]  # importer package parts
        if level - 1 > len(importer_package_parts):
            return []
        base: list[str] = (
            importer_package_parts[: len(importer_package_parts) - (level - 1)]
            if level > 1
            else importer_package_parts
        )
        if not rest:
            # ``from . import d``: the package itself.
            return [".".join(base)] if base else []
        full: list[str] = base + rest.split(".")
        keys: list[str] = [".".join(full)]
        # Above-root fallback: strip leading components.
        for i in range(1, len(full)):
            keys.append(".".join(full[i:]))
        return keys
    parts = [p for p in module_specifier.split(".") if p]
    keys = [".".join(parts[i:]) for i in range(len(parts))]
    return keys


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


def extract_nodes_and_edges(
    rel_path: str,
    syntax_root: Node,
    graph_root: str,
    total_lines: int,
    dotted_module_to_rel_path: Mapping[str, str],
) -> ExtractedFileGraph:
    """Walk one Python file once, emitting nodes + edges inline.

    - defs → ``Node`` + ``Edge(CONTAINS)`` with ``base:name:start:end`` ids.
    - imports → ``Node(IMPORT)`` + ``Edge(IMPORTS)`` (existing statement rules).
    - bare calls with a live enclosing def → same-file hit by name, else
      assumed ``base:name`` edge via ``dotted_module_to_rel_path``; natives (no def, no
      import) are dropped and stored nowhere.
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
    emitted_edge_keys: set[tuple[str, str, str]] = set()
    first_def_node_id_by_name: dict[str, str] = {}
    module_specifier_by_bound_name: dict[str, str] = {}
    deferred_call_sites: list[tuple[str, str, int]] = []

    for syntax_node in walk(syntax_root):
        if syntax_node.type in ("class_definition", "function_definition"):
            _pop_finished_definitions(
                active_definition_stack, syntax_node.start_byte
            )
            def_name: str = _definition_name(syntax_node)
            if not def_name:
                continue
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
        for module_lookup_key in _module_index_lookup_keys(
            imported_module_specifier, rel_path
        ):
            indexed_rel_path: str | None = dotted_module_to_rel_path.get(
                module_lookup_key
            )
            if indexed_rel_path is not None:
                resolved_callee_rel_path = indexed_rel_path
                break
        if resolved_callee_rel_path is None:
            continue  # stdlib / third-party / unindexed: drop
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


__all__ = [
    "ExtractedFileGraph",
    "LANGUAGE",
    "build_assumed_callee_id",
    "build_defined_node_id",
    "extract_nodes_and_edges",
]
