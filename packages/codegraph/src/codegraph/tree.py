"""Hierarchy-tree snapshot + renderer for the code graph.

:func:`load_snapshot` reads one root's rows; :func:`render_tree` turns
them into a nested unicode tree (pure, no I/O — unit-testable).
``contains`` edges drive the nesting (file → def, class → method,
function → nested def); ``calls`` edges (caller → callee) render as a
``calls (N)`` subgroup under each function; ``imports`` edges render as
a leaf group carrying each edge's ``target_module``.
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


def kind_label(kind: NodeKind | EdgeKind | str) -> str:
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
        (n for n in snapshot.nodes if kind_label(n.kind) == "file"),
        key=lambda n: n.file_path,
    )
    by_id: dict[str, Node] = {n.id: n for n in snapshot.nodes}
    contains: dict[str, list[str]] = {}
    calls: dict[str, list[str]] = {}
    import_targets: dict[str, str | None] = {}
    for edge in snapshot.edges:
        label: str = kind_label(edge.kind)
        if label == "contains":
            contains.setdefault(edge.src_id, []).append(edge.dst_id)
        elif label == "calls":
            calls.setdefault(edge.src_id, []).append(edge.dst_id)
        elif label == "imports":
            contains.setdefault(edge.src_id, []).append(edge.dst_id)
            import_targets[edge.dst_id] = edge.target_module

    def ordered(node_ids: list[str]) -> list[Node]:
        """Resolve ids to nodes, ordered by start line."""
        resolved: list[Node] = [by_id[i] for i in node_ids if i in by_id]
        resolved.sort(key=lambda n: (n.start_line, n.name))
        return resolved

    def render_children(prefix: str, node: Node, lines: list[str]) -> None:
        """Render the subtree under one def node.

        Classes show methods as leaves; functions show nested classes
        as nested blocks plus a ``calls (N)`` subgroup of function-kind
        callees. Every node appears exactly once.
        """
        label: str = kind_label(node.kind)
        if label == "class":
            methods: list[Node] = [
                m
                for m in ordered(contains.get(node.id, []))
                if kind_label(m.kind) == "function"
            ]
            for method_index, method in enumerate(methods):
                last: bool = method_index == len(methods) - 1
                branch: str = branch_last if last else branch_mid
                lines.append(f"{prefix}{branch}function {method.name} {_span(method)}")
        elif label == "function":
            nested: list[Node] = [
                n
                for n in ordered(contains.get(node.id, []))
                if kind_label(n.kind) == "class"
            ]
            callees: list[Node] = [
                n
                for n in ordered(calls.get(node.id, []))
                if kind_label(n.kind) == "function"
            ]
            # Each block is (header, nested node XOR leaf lines).
            blocks: list[tuple[str, Node | None, list[str]]] = [
                (f"class {n.name} {_span(n)}", n, []) for n in nested
            ]
            if callees:
                blocks.append((
                    f"calls ({len(callees)})",
                    None,
                    [f"function {c.name} {_span(c)}" for c in callees],
                ))
            for block_index, (header, nested_node, leaves) in enumerate(blocks):
                last_block: bool = block_index == len(blocks) - 1
                branch = branch_last if last_block else branch_mid
                lines.append(f"{prefix}{branch}{header}")
                stem: str = stem_last if last_block else stem_mid
                if nested_node is not None:
                    render_children(f"{prefix}{stem}", nested_node, lines)
                else:
                    for leaf_index, leaf in enumerate(leaves):
                        leaf_branch: str = (
                            branch_last
                            if leaf_index == len(leaves) - 1
                            else branch_mid
                        )
                        lines.append(f"{prefix}{stem}{leaf_branch}{leaf}")

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
        contained: list[Node] = ordered(contains.get(file_node.id, []))
        classes: list[Node] = [n for n in contained if kind_label(n.kind) == "class"]
        top_functions: list[Node] = [
            n for n in contained if kind_label(n.kind) == "function"
        ]
        imports: list[Node] = [
            n for n in contained if kind_label(n.kind) == "import"
        ]
        def_blocks: list[Node] = classes + top_functions
        has_imports: bool = len(imports) > 0
        for block_index, def_node in enumerate(def_blocks):
            last_block: bool = block_index == len(def_blocks) - 1 and not has_imports
            branch = branch_last if last_block else branch_mid
            lines.append(
                f"{branch}{kind_label(def_node.kind)} {def_node.name} "
                f"{_span(def_node)}"
            )
            stem = stem_last if last_block else stem_mid
            render_children(stem, def_node, lines)
        if imports:
            lines.append(f"{branch_last}imports ({len(imports)})")
            for leaf_index, node in enumerate(imports):
                leaf_branch = (
                    branch_last if leaf_index == len(imports) - 1 else branch_mid
                )
                lines.append(
                    f"{stem_last}{leaf_branch}{node.name} -> "
                    f"{import_targets.get(node.id) or '?'} (L{node.start_line})"
                )
    return "\n".join(lines)


__all__ = ["GraphSnapshot", "kind_label", "load_snapshot", "render_tree"]
