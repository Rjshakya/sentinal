"""Go structural extraction from a raw tree-sitter tree.

Pure: takes the parsed ``root``, returns defs + imports. Struct types
map to ``class`` nodes; functions and methods keep their Go names.
"""

from __future__ import annotations

import posixpath
from collections.abc import Mapping
from dataclasses import dataclass
from dataclasses import field as dc_field
from pathlib import Path
from typing import TYPE_CHECKING

from tree_sitter import Node

from codegraph.models import Edge, EdgeKind
from codegraph.models import Node as GraphNode
from codegraph.models import NodeKind
from codegraph.parser.base import ParsedDefinition, ParsedImport
from codegraph.parser.raw_core import field_text, node_text, parse, span, walk

if TYPE_CHECKING:
    from codegraph.parser.rows import FileRows

LANGUAGE: str = "go"


def extract_definitions(root: Node) -> list[ParsedDefinition]:
    """Collect struct types, functions, and methods in source order (preorder)."""
    found: list[ParsedDefinition] = []
    scope: list[tuple[str, str]] = []  # enclosing (kind, name)
    stack: list[tuple[Node, bool]] = [(root, False)]  # True = exit, pops scope
    while stack:
        node, exiting = stack.pop()
        if exiting:
            scope.pop()
            continue
        parent: str | None = scope[-1][1] if scope else None
        if node.type == "function_declaration":
            name: str = field_text(node, "name")
            kind: str = "function"
        elif node.type == "method_declaration":
            name_node: Node | None = node.child_by_field_name("name")
            name = node_text(name_node) if name_node is not None else ""
            kind = "method"
            if parent is None:
                parent = _receiver_base(node)
        elif node.type == "type_spec":
            name = field_text(node, "name")
            kind = "class"
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
                parent=parent,
            )
        )
        scope.append(("class" if kind == "class" else "function", name))
        stack.append((node, True))
        for child in reversed(node.named_children):
            stack.append((child, False))
    return found


def _receiver_base(node: Node) -> str | None:
    """Return the receiver's base type name (``*S`` -> ``S``), if any."""
    receiver: Node | None = node.child_by_field_name("receiver")
    if receiver is None:
        return None
    candidates: list[str] = []
    stack: list[Node] = [receiver]
    while stack:
        probe: Node = stack.pop()
        if probe.type == "type_identifier":
            candidates.append(node_text(probe))
        stack.extend(probe.named_children)
    return candidates[-1] if candidates else None


def _import_name(module: str, explicit: str) -> str:
    if explicit and explicit not in ("_", "."):
        return explicit
    if explicit in ("_", "."):
        return "*"
    # Default: base of the module path (quoted path without quotes).
    base: str = module.rsplit("/", 1)[-1]
    return base or "*"


def extract_imports(root: Node) -> list[ParsedImport]:
    """Collect imports from ``import_spec`` nodes."""
    found: list[ParsedImport] = []
    for node in walk(root):
        if node.type != "import_spec":
            continue
        module: str = field_text(node, "path").strip().strip('"').strip("`").strip()
        if not module:
            continue
        explicit: str = field_text(node, "name").strip()
        name: str = _import_name(module, explicit)
        start, end = span(node)
        found.append(
            ParsedImport(module=module, name=name, start_line=start, end_line=end)
        )
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


def _is_struct_spec(syntax_node: Node) -> bool:
    """Return True when a ``type_spec`` declares a struct type."""
    for child in syntax_node.named_children:
        if child.type == "struct_type":
            return True
    return False


def _go_lookup_keys(module_specifier: str, importer_rel_path: str) -> list[str]:
    """Return candidate rel paths for a relative Go import."""
    if not module_specifier.startswith("."):
        return []
    base: str = posixpath.normpath(
        posixpath.join(posixpath.dirname(importer_rel_path), module_specifier)
    )
    return [base, base + ".go"]


def _go_tail_candidates(
    module_specifier: str, import_index: Mapping[str, str]
) -> list[str]:
    """Return indexed ``.go`` rel paths whose stem matches the import tail."""
    tail: str = module_specifier.rsplit("/", 1)[-1]
    if not tail:
        return []
    matches: set[str] = {
        rel_path
        for rel_path in set(import_index.values())
        if rel_path.endswith(".go") and Path(rel_path).stem == tail
    }
    return sorted(matches, key=lambda p: (len(p), p))


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
    """Walk one Go file once, emitting nodes + edges inline.

    - struct ``type_spec`` → ``Node(CLASS)``, funcs/methods → ``Node`` +
      ``Edge(CONTAINS)`` with ``base:name:start:end`` ids.
    - ``import_spec`` → ``Node(IMPORT)`` + ``Edge(IMPORTS)``.
    - bare calls with a live enclosing def → same-file hit by name, else
      assumed ``base:name`` edge via ``import_index``; natives (no def,
      no import) are dropped and stored nowhere.
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
    active_definition_stack: list[_ActiveDefinition] = []
    emitted_edge_keys: set[tuple[str, str, str]] = set()
    first_def_node_id_by_name: dict[str, str] = {}
    struct_node_id_by_name: dict[str, str] = {}
    method_receiver_by_node_id: dict[str, str] = {}
    module_specifier_by_bound_name: dict[str, str] = {}
    deferred_call_sites: list[tuple[str, str, int]] = []

    for syntax_node in walk(syntax_root):
        if syntax_node.type in (
            "function_declaration",
            "method_declaration",
        ) or (
            syntax_node.type == "type_spec" and _is_struct_spec(syntax_node)
        ):
            _pop_finished_definitions(
                active_definition_stack, syntax_node.start_byte
            )
            def_name: str = field_text(syntax_node, "name")
            if not def_name:
                continue
            if syntax_node.type == "type_spec":
                graph_node_kind: NodeKind = NodeKind.CLASS
                stack_kind: str = "class"
            elif syntax_node.type == "method_declaration":
                graph_node_kind = NodeKind.METHOD
                stack_kind = "function"
            else:
                graph_node_kind = NodeKind.FUNCTION
                stack_kind = "function"
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
            if syntax_node.type == "type_spec":
                struct_node_id_by_name.setdefault(def_name, definition_node_id)
            elif syntax_node.type == "method_declaration":
                receiver: str | None = _receiver_base(syntax_node)
                if receiver:
                    method_receiver_by_node_id.setdefault(
                        definition_node_id, receiver
                    )
            active_definition_stack.append(
                _ActiveDefinition(
                    def_kind=stack_kind,
                    def_name=def_name,
                    node_id=definition_node_id,
                    end_byte=syntax_node.end_byte,
                )
            )
        elif syntax_node.type == "import_spec":
            module: str = (
                field_text(syntax_node, "path").strip().strip('"').strip("`").strip()
            )
            if not module:
                continue
            explicit: str = field_text(syntax_node, "name").strip()
            bound_name: str = _import_name(module, explicit)
            if not bound_name:
                continue
            start_line, end_line = span(syntax_node)
            import_node_id: str = f"{rel_path}:import:{bound_name}:{start_line}"
            _register_node_once(
                extracted_file.nodes,
                node_id=import_node_id,
                graph_root=graph_root,
                rel_path=rel_path,
                language=language,
                kind=NodeKind.IMPORT,
                name=bound_name,
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
                target_module=module,
            )
            module_specifier_by_bound_name.setdefault(bound_name, module)
        else:
            callee_name: str | None = _bare_callee_name(syntax_node)
            if callee_name is None:
                continue
            _pop_finished_definitions(
                active_definition_stack, syntax_node.start_byte
            )
            if not active_definition_stack:
                continue  # package-level call: drop
            call_site_line: int = span(syntax_node)[0]
            deferred_call_sites.append(
                (active_definition_stack[-1].node_id, callee_name, call_site_line)
            )

    for method_node_id, receiver_name in method_receiver_by_node_id.items():
        struct_node_id: str | None = struct_node_id_by_name.get(receiver_name)
        if struct_node_id is None:
            continue
        method_node: GraphNode | None = extracted_file.nodes.get(method_node_id)
        if method_node is None or method_node.parent_id != rel_path:
            continue
        method_node.parent_id = struct_node_id
        for edge in extracted_file.edges:
            if (
                edge.kind == EdgeKind.CONTAINS
                and edge.dst_id == method_node_id
                and edge.src_id == rel_path
            ):
                edge.src_id = struct_node_id
                edge.id = f"{struct_node_id}::{edge.kind.value}::{method_node_id}"
                break

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
            continue  # builtin / unknown: store nothing
        resolved_callee_rel_path: str | None = None
        for module_lookup_key in _go_lookup_keys(
            imported_module_specifier, rel_path
        ):
            indexed_rel_path: str | None = import_index.get(module_lookup_key)
            if indexed_rel_path is not None:
                resolved_callee_rel_path = indexed_rel_path
                break
        if resolved_callee_rel_path is None and not imported_module_specifier.startswith(
            "."
        ):
            tail_candidates: list[str] = _go_tail_candidates(
                imported_module_specifier, import_index
            )
            if tail_candidates:
                resolved_callee_rel_path = tail_candidates[0]
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


def build_go_file_rows(
    root: str,
    rel_path: str,
    source_text: str,
    import_index: Mapping[str, str],
) -> FileRows:
    """Build one Go file's rows (same contract as ``build_python_file_rows``)."""
    from codegraph.parser.rows import FileRows

    total_lines: int = max(source_text.count("\n") + 1, 1)
    rows = FileRows(rel_path=rel_path, language=LANGUAGE)
    if not source_text.strip():
        rows.nodes.append(
            GraphNode(
                id=rel_path,
                root=root,
                file_path=rel_path,
                kind=NodeKind.FILE,
                name=Path(rel_path).name,
                language=LANGUAGE,
                start_line=1,
                end_line=total_lines,
                parent_id=None,
            )
        )
        return rows
    tree = parse(LANGUAGE, source_text.encode("utf-8"))
    out: ExtractedFileGraph = extract_nodes_and_edges(
        rel_path, tree.root_node, root, total_lines, import_index
    )
    rows.nodes.extend(out.nodes.values())
    rows.edges.extend(out.edges)
    return rows


__all__ = [
    "ExtractedFileGraph",
    "LANGUAGE",
    "build_assumed_callee_id",
    "build_defined_node_id",
    "build_go_file_rows",
    "extract_definitions",
    "extract_imports",
    "extract_nodes_and_edges",
]
