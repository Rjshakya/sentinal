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

    Links (all derived from the tree-sitter structure hierarchy):

    - ``contains``: file → each top-level def; class → each method;
      function → each nested def.
    - ``calls`` (caller → callee): function → each nested def. Methods
      are excluded — they render under their class, not as callees.
    - ``imports``: file → each imported name (carries ``target_module``).

    The file node always exists, even for empty files. Definitions are
    visited in preorder, so a parent's node id is always registered
    before its children resolve it. Duplicate names in one file resolve
    to the first registration.
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

    def_ids: dict[str, str] = {}
    def_kinds: dict[str, str] = {}
    for definition in parsed.definitions:
        node_id: str = new_id()
        parent_id: str = file_id
        if definition.parent is not None and definition.parent in def_ids:
            parent_id = def_ids[definition.parent]
        kind = NodeKind.CLASS if definition.kind == "class" else NodeKind.FUNCTION
        nodes.append(
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
        # Caller → callee: a def nested in a *function* is its callee.
        # Methods (nested in a class) are excluded — they render under
        # their class, not as callees.
        if (
            definition.parent is not None
            and definition.parent in def_ids
            and def_kinds.get(definition.parent) == "function"
        ):
            edges.append(
                Edge(
                    id=new_id(),
                    root=root,
                    src_id=parent_id,
                    dst_id=node_id,
                    kind=EdgeKind.CALLS,
                    target_module=None,
                )
            )
        def_ids.setdefault(definition.name, node_id)
        def_kinds.setdefault(definition.name, definition.kind)

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
