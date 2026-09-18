"""Parser dispatch and graph builder.

:func:`parse_file` picks the language parser by extension (via
``walk.EXT_TO_LANGUAGE``). :func:`build_graph_rows` converts the
resulting :class:`ParsedFile` IR into ``Node`` / ``Edge`` rows with
stable parent links — the single place where IR becomes storage rows.
"""

from __future__ import annotations

from pathlib import Path

from codegraph.models import Edge, EdgeKind, Node, NodeKind, new_id
from codegraph.parser.base import ParsedFile
from codegraph.parser.python import parse_python_source
from codegraph.parser.typescript import (
    parse_javascript_source,
    parse_typescript_source,
)


def parse_source_text(language: str, source_text: str) -> ParsedFile:
    """Dispatch source text to the language parser.

    Raises:
        ValueError: for languages outside the v1 set.
    """
    if language == "python":
        return parse_python_source(source_text)
    if language == "typescript":
        return parse_typescript_source(source_text)
    if language == "javascript":
        return parse_javascript_source(source_text)
    raise ValueError(f"unsupported language: {language!r}")


def parse_file(path: Path, language: str) -> ParsedFile:
    """Read ``path`` and parse it (sync; callers wrap in ``to_thread``)."""
    return parse_source_text(language, path.read_text(encoding="utf-8", errors="ignore"))


def build_graph_rows(
    root: str,
    rel_path: str,
    language: str,
    parsed: ParsedFile,
) -> tuple[list[Node], list[Edge]]:
    """Convert a :class:`ParsedFile` into ``Node`` / ``Edge`` rows.

    Parent links: a method's parent is the class node with the matching
    name in the same file; anything else hangs off the file node. The
    file node always exists, even for empty files.
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
    nodes: list[Node] = [file_node]
    edges: list[Edge] = []

    class_ids: dict[str, str] = {}
    for definition in parsed.definitions:
        if definition.kind == "class":
            node_id: str = new_id()
            class_ids[definition.name] = node_id
            nodes.append(
                Node(
                    id=node_id,
                    root=root,
                    file_path=rel_path,
                    kind=NodeKind.CLASS,
                    name=definition.name,
                    language=language,
                    start_line=definition.start_line,
                    end_line=definition.end_line,
                    parent_id=file_id,
                )
            )
            edges.append(
                Edge(
                    id=new_id(),
                    root=root,
                    src_id=file_id,
                    dst_id=node_id,
                    kind=EdgeKind.CONTAINS,
                    target_module=None,
                )
            )

    for definition in parsed.definitions:
        if definition.kind != "function":
            continue
        parent_id: str = file_id
        if definition.parent is not None and definition.parent in class_ids:
            parent_id = class_ids[definition.parent]
        node_id = new_id()
        nodes.append(
            Node(
                id=node_id,
                root=root,
                file_path=rel_path,
                kind=NodeKind.FUNCTION,
                name=definition.name,
                language=language,
                start_line=definition.start_line,
                end_line=definition.end_line,
                parent_id=parent_id,
            )
        )
        edges.append(
            Edge(
                id=new_id(),
                root=root,
                src_id=parent_id,
                dst_id=node_id,
                kind=EdgeKind.CONTAINS,
                target_module=None,
            )
        )

    for imported in parsed.imports:
        node_id = new_id()
        nodes.append(
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
        edges.append(
            Edge(
                id=new_id(),
                root=root,
                src_id=file_id,
                dst_id=node_id,
                kind=EdgeKind.IMPORTS,
                target_module=imported.module,
            )
        )

    return (nodes, edges)


__all__ = ["build_graph_rows", "parse_file", "parse_source_text"]
