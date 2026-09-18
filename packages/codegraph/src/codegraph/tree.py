"""Hierarchy-tree snapshot + renderer for the code graph.

:func:`load_snapshot` reads one root's rows; :func:`render_tree` turns
them into a nested unicode tree (pure, no I/O — unit-testable).
``contains`` edges drive the nesting (file → class/function,
class → method); ``imports`` edges render as a leaf group carrying
each edge's ``target_module``.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from typing import TYPE_CHECKING

from codegraph.models import Edge, EdgeKind, Node, NodeKind

if TYPE_CHECKING:
    from codegraph.store import GraphStore


@dataclass(frozen=True, slots=True)
class GraphSnapshot:
    """All rows of one indexed root, ready to render."""

    root: str
    nodes: tuple[Node, ...]
    edges: tuple[Edge, ...]


async def load_snapshot(store: GraphStore, root: str) -> GraphSnapshot:
    """Load every node/edge of ``root`` into a :class:`GraphSnapshot`."""
    nodes: list[Node] = await store.list_nodes(root=root)
    edges: list[Edge] = await store.list_edges(root=root)
    return GraphSnapshot(root=root, nodes=tuple(nodes), edges=tuple(edges))


def _kind_label(kind: NodeKind | EdgeKind | str) -> str:
    """Normalise a kind to its plain lowercase value (``file``, …)."""
    if isinstance(kind, enum.Enum):
        return str(kind.value).lower()
    text: str = str(kind)
    if "." in text:
        text = text.rsplit(".", 1)[-1]
    return text.lower()


def _span(node: Node) -> str:
    """Format a node's line range as ``(Lstart-Lend)``."""
    return f"(L{node.start_line}-L{node.end_line})"


def render_tree(snapshot: GraphSnapshot, *, use_unicode: bool = True) -> str:
    """Render ``snapshot`` as a nested hierarchy tree.

    ``use_unicode=False`` selects an ASCII-safe glyph set for consoles
    whose encoding cannot represent box-drawing characters (e.g. the
    Windows cp1252 console).
    """
    branch_last: str = "└── " if use_unicode else "`-- "
    branch_mid: str = "├── " if use_unicode else "|-- "
    stem_last: str = "    "
    stem_mid: str = "│   " if use_unicode else "|   "
    files: list[Node] = sorted(
        (n for n in snapshot.nodes if _kind_label(n.kind) == "file"),
        key=lambda n: n.file_path,
    )
    by_id: dict[str, Node] = {n.id: n for n in snapshot.nodes}
    children: dict[str, list[str]] = {}
    import_targets: dict[str, str | None] = {}
    for edge in snapshot.edges:
        if _kind_label(edge.kind) == "contains":
            children.setdefault(edge.src_id, []).append(edge.dst_id)
        elif _kind_label(edge.kind) == "imports":
            children.setdefault(edge.src_id, []).append(edge.dst_id)
            import_targets[edge.dst_id] = edge.target_module

    def ordered(node_ids: list[str]) -> list[Node]:
        """Resolve ids to nodes, ordered by start line."""
        resolved: list[Node] = [by_id[i] for i in node_ids if i in by_id]
        resolved.sort(key=lambda n: (n.start_line, n.name))
        return resolved

    lines: list[str] = [
        f"root: {snapshot.root}  "
        f"(files={len(files)} nodes={len(snapshot.nodes)} "
        f"edges={len(snapshot.edges)})"
    ]
    for file_index, file_node in enumerate(files):
        if file_index > 0:
            lines.append("")
        lines.append(
            f"file {file_node.file_path} [{file_node.language}] {_span(file_node)}"
        )
        contained: list[Node] = ordered(children.get(file_node.id, []))
        classes: list[Node] = [n for n in contained if _kind_label(n.kind) == "class"]
        top_functions: list[Node] = [
            n for n in contained if _kind_label(n.kind) == "function"
        ]
        imports: list[Node] = [
            n for n in contained if _kind_label(n.kind) == "import"
        ]
        blocks: list[tuple[str, list[str]]] = []
        for cls in classes:
            method_lines: list[str] = [
                f"function {m.name} {_span(m)}"
                for m in ordered(children.get(cls.id, []))
                if _kind_label(m.kind) == "function"
            ]
            blocks.append((f"class {cls.name} {_span(cls)}", method_lines))
        for func in top_functions:
            blocks.append((f"function {func.name} {_span(func)}", []))
        if imports:
            blocks.append((
                f"imports ({len(imports)})",
                [
                    f"{node.name} -> {import_targets.get(node.id) or '?'} "
                    f"(L{node.start_line})"
                    for node in imports
                ],
            ))
        for block_index, (header, leaves) in enumerate(blocks):
            last_block: bool = block_index == len(blocks) - 1
            branch: str = branch_last if last_block else branch_mid
            lines.append(f"{branch}{header}")
            stem: str = stem_last if last_block else stem_mid
            for leaf_index, leaf in enumerate(leaves):
                leaf_branch: str = (
                    branch_last if leaf_index == len(leaves) - 1 else branch_mid
                )
                lines.append(f"{stem}{leaf_branch}{leaf}")
    return "\n".join(lines)


__all__ = ["GraphSnapshot", "load_snapshot", "render_tree"]
