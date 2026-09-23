"""Per-file row builders: source text -> storage rows (pure)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from codegraph.models import Edge, EdgeKind, Node, NodeKind, new_id
from codegraph.parser.base import ParsedCall, ParsedFile
from codegraph.parser.raw_core import parse


@dataclass(slots=True)
class FileRows:
    """Per-file build output: storage rows plus resolution maps."""

    rel_path: str
    language: str
    nodes: list[Node] = field(default_factory=lambda: list[Node]())
    edges: list[Edge] = field(default_factory=lambda: list[Edge]())
    definitions: dict[str, str] = field(default_factory=lambda: dict[str, str]())
    imports: dict[str, str] = field(default_factory=lambda: dict[str, str]())
    calls: list[ParsedCall] = field(default_factory=lambda: list[ParsedCall]())


def _node_kind(kind: str) -> NodeKind:
    if kind == "class":
        return NodeKind.CLASS
    if kind == "method":
        return NodeKind.METHOD
    if kind == "function":
        return NodeKind.FUNCTION
    return NodeKind.FUNCTION


def build_file_rows(
    root: str,
    rel_path: str,
    language: str,
    parsed: ParsedFile,
) -> FileRows:
    """Convert one :class:`ParsedFile` into nodes + ``contains`` / ``imports``.

    ``calls`` edges are NOT emitted here — they resolve across files in
    ``links.resolve_call_edges``. The file node always exists, even for
    empty files. Duplicate names in one file resolve to the first
    registration.
    """
    file_id: str = new_id()
    file_node = Node(
        id=file_id,
        root=root,
        file_path=rel_path,
        kind=NodeKind.FILE,
        name=Path(rel_path).name,
        language=language,
        start_line=1,
        end_line=parsed.total_lines,
        parent_id=None,
    )
    rows = FileRows(rel_path=rel_path, language=language)
    rows.nodes.append(file_node)

    def_ids: dict[str, str] = {}
    for definition in parsed.definitions:
        node_id: str = new_id()
        parent_id: str = file_id
        if definition.parent is not None and definition.parent in def_ids:
            parent_id = def_ids[definition.parent]
        kind = _node_kind(definition.kind)
        rows.nodes.append(
            Node(
                id=node_id,
                root=root,
                file_path=rel_path,
                kind=kind,
                name=definition.name,
                language=language,
                start_line=definition.start_line,
                end_line=definition.end_line,
                parent_id=parent_id,
            )
        )
        rows.edges.append(
            Edge(
                id=new_id(),
                root=root,
                src_id=parent_id,
                dst_id=node_id,
                kind=EdgeKind.CONTAINS,
                target_module=None,
            )
        )
        def_ids.setdefault(definition.name, node_id)
        rows.definitions.setdefault(definition.name, node_id)

    for imported in parsed.imports:
        node_id = new_id()
        rows.nodes.append(
            Node(
                id=node_id,
                root=root,
                file_path=rel_path,
                kind=NodeKind.IMPORT,
                name=imported.name,
                language=language,
                start_line=imported.start_line,
                end_line=imported.end_line,
                parent_id=file_id,
            )
        )
        rows.edges.append(
            Edge(
                id=new_id(),
                root=root,
                src_id=file_id,
                dst_id=node_id,
                kind=EdgeKind.IMPORTS,
                target_module=imported.module,
            )
        )
        rows.imports.setdefault(imported.name, imported.module)

    rows.calls.extend(parsed.calls)
    return rows


def build_python_file_rows(
    root: str,
    rel_path: str,
    source_text: str,
    import_index: Mapping[str, str],
) -> FileRows:
    """Build one Python file's rows via the v2 single-pass emitter.

    Nodes + ``contains`` / ``imports`` / ``calls`` edges (same-file hits
    and assumed cross-file refs) come out of
    :func:`lang_python.extract_nodes_and_edges` directly; ``calls`` needs
    no global pass, so the returned ``calls`` list stays empty.
    """
    from codegraph.parser import lang_python

    total_lines: int = max(source_text.count("\n") + 1, 1)
    rows = FileRows(rel_path=rel_path, language="python")
    if not source_text.strip():
        file_node = Node(
            id=rel_path,
            root=root,
            file_path=rel_path,
            kind=NodeKind.FILE,
            name=Path(rel_path).name,
            language="python",
            start_line=1,
            end_line=total_lines,
            parent_id=None,
        )
        rows.nodes.append(file_node)
        return rows
    tree = parse("python", source_text.encode("utf-8"))

    out = lang_python.extract_nodes_and_edges(
        rel_path, tree.root_node, root, total_lines, import_index
    )
    rows.nodes.extend(out.nodes.values())
    rows.edges.extend(out.edges)
    return rows


__all__ = [
    "FileRows",
    "build_file_rows",
    "build_python_file_rows",
]
