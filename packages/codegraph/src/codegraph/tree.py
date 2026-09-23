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
    by_file_name: dict[tuple[str, str], Node] = {}
    for n in sorted(snapshot.nodes, key=lambda x: (x.file_path, x.start_line)):
        if kind_label(n.kind) in ("class", "function", "method"):
            by_file_name.setdefault((n.file_path, n.name), n)
    contains: dict[str, list[str]] = {}
    calls: dict[str, list[Edge]] = {}
    import_targets: dict[str, str | None] = {}
    for edge in snapshot.edges:
        label: str = kind_label(edge.kind)
        if label == "contains":
            contains.setdefault(edge.src_id, []).append(edge.dst_id)
        elif label == "calls":
            calls.setdefault(edge.src_id, []).append(edge)
        elif label == "imports":
            contains.setdefault(edge.src_id, []).append(edge.dst_id)
            import_targets[edge.dst_id] = edge.target_module

    def ordered(node_ids: list[str]) -> list[Node]:
        """Resolve ids to nodes, ordered by start line."""
        resolved: list[Node] = [by_id[i] for i in node_ids if i in by_id]
        resolved.sort(key=lambda n: (n.start_line, n.name))
        return resolved

    def _callee_sort_key(call: Edge) -> tuple[int, int, int, str]:
        """Order callees by implementation order: call-site line first.

        Edges without a site line (non-Python path, older rows) fall
        back to the callee def's start line, then name — never worse
        than the old alphabetical order.
        """
        node: Node | None = by_id.get(call.dst_id)
        if node is None and len(call.dst_id.split(":")) == 2:
            target_rel, name = call.dst_id.split(":")
            node = by_file_name.get((target_rel, name))
        def_start: int = node.start_line if node is not None else 1 << 30
        if call.site_line is not None:
            return (0, call.site_line, def_start, "")
        return (1, def_start, 1 << 30, node.name if node is not None else call.dst_id)

    def ordered_callees(call_edges: list[Edge]) -> list[str]:
        """Render each calls dst in implementation order; assumed refs resolve via (file, name).

        Returns display lines. A miss (no node with that name in the
        target file) renders as ``name -> target (missing)`` — the
        broken-import signal.
        """
        lines: list[str] = []
        for call in sorted(call_edges, key=_callee_sort_key):
            dst_id: str = call.dst_id
            node: Node | None = by_id.get(dst_id)
            if node is not None:
                lines.append(f"{kind_label(node.kind)} {node.name} {_span(node)}")
                continue
            parts: list[str] = dst_id.split(":")
            if len(parts) == 2:
                target_rel, name = parts
                hit: Node | None = by_file_name.get((target_rel, name))
                if hit is not None:
                    lines.append(f"{kind_label(hit.kind)} {hit.name} {_span(hit)}")
                else:
                    lines.append(f"{name} -> {target_rel} (missing)")
            else:
                lines.append(f"{dst_id} (missing)")
        return lines

    def render_children(prefix: str, node: Node, lines: list[str]) -> None:
        """Render the subtree under one def node.

        Classes show methods as leaves; functions and methods show
        nested classes as nested blocks plus a ``calls (N)`` subgroup.
        Every node appears exactly once.
        """
        label: str = kind_label(node.kind)
        if label == "class":
            methods: list[Node] = [
                m
                for m in ordered(contains.get(node.id, []))
                if kind_label(m.kind) == "method"
            ]
            for method_index, method in enumerate(methods):
                last: bool = method_index == len(methods) - 1
                branch: str = branch_last if last else branch_mid
                lines.append(f"{prefix}{branch}method {method.name} {_span(method)}")
                render_children_calls_only(f"{prefix}{stem_last if last else stem_mid}", method, lines)
        elif label in ("function", "method"):
            nested: list[Node] = [
                n
                for n in ordered(contains.get(node.id, []))
                if kind_label(n.kind) == "class"
            ]
            callee_lines: list[str] = ordered_callees(calls.get(node.id, []))
            # Each block is (header, nested node XOR leaf lines).
            blocks: list[tuple[str, Node | None, list[str]]] = [
                (f"class {n.name} {_span(n)}", n, []) for n in nested
            ]
            if callee_lines:
                blocks.append((f"calls ({len(callee_lines)})", None, callee_lines))
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

    def render_children_calls_only(prefix: str, node: Node, lines: list[str]) -> None:
        """Render only the ``calls`` subgroup under a method leaf."""
        callee_lines: list[str] = ordered_callees(calls.get(node.id, []))
        if not callee_lines:
            return
        lines.append(f"{prefix}{branch_last}calls ({len(callee_lines)})")
        for leaf_index, leaf in enumerate(callee_lines):
            leaf_branch = branch_last if leaf_index == len(callee_lines) - 1 else branch_mid
            lines.append(f"{prefix}{stem_last}{leaf_branch}{leaf}")

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
        top_methods: list[Node] = [
            n for n in contained if kind_label(n.kind) == "method"
        ]
        imports: list[Node] = [
            n for n in contained if kind_label(n.kind) == "import"
        ]
        def_blocks: list[Node] = classes + top_functions + top_methods
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
