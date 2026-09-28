"""Agent-facing query shaping: explore-first access to the code graph.

Agents never know node id shapes, so every exploration starts from
`files` (file ids are plain rel paths) or `search` (a name fragment
-> full rows with ids), then drills via `node` / `callees` /
`callers` / `children` / `imports` using the discovered ids. All
functions here are pure given store rows; I/O lives in `cli.py`.

JSON envelope (stable keys for chaining):
`{"root", "verb", "count", "truncated", "items": [...]}` where each
item is `{"id", "kind", "name", "file_path", "language",
"start_line", "end_line", "parent_id"}` plus `site_line` on
`callees` / `callers` items and `target_module` on `imports` items.
"""

from __future__ import annotations

from typing import Any

from codegraph.models import Node
from codegraph.tree import kind_label

DEFAULT_SEARCH_LIMIT: int = 20
"""Cap for `search` hits; excess sets `truncated` so agents narrow down."""


def to_item(node: Node) -> dict[str, Any]:
    """Project a node onto its stable JSON item shape."""
    return {
        "id": node.id,
        "kind": kind_label(node.kind),
        "name": node.name,
        "file_path": node.file_path,
        "language": node.language,
        "start_line": node.start_line,
        "end_line": node.end_line,
        "parent_id": node.parent_id,
    }


def envelope(root: str, verb: str, items: list[dict[str, Any]]) -> dict[str, Any]:
    """Wrap result items in the stable chaining envelope."""
    return {
        "root": root,
        "verb": verb,
        "count": len(items),
        "truncated": False,
        "items": items,
    }


def search_nodes(
    nodes: list[Node],
    fragment: str,
    *,
    kind: str | None = None,
    file_path: str | None = None,
    limit: int = DEFAULT_SEARCH_LIMIT,
) -> tuple[list[Node], bool]:
    """Substring-match def names (case-insensitive), in stable order.

    Returns ``(hits, truncated)``. File nodes never match — `files`
    lists those. ``kind`` / ``file_path`` narrow exact (kind is
    matched case-insensitively on its plain value).
    """
    needle: str = fragment.strip().lower()
    wanted_kind: str | None = kind.strip().lower() if kind else None
    hits: list[Node] = [
        node
        for node in nodes
        if kind_label(node.kind) != "file"
        and (not needle or needle in node.name.lower())
        and (wanted_kind is None or kind_label(node.kind) == wanted_kind)
        and (file_path is None or node.file_path == file_path)
    ]
    hits.sort(key=lambda n: (n.file_path, n.start_line, n.name))
    if len(hits) > limit:
        return (hits[:limit], True)
    return (hits, False)


def exact_matches(
    nodes: list[Node], name: str, file_path: str | None = None
) -> list[Node]:
    """Exact-name matches (file nodes excluded), in stable order.

    Backs ``--name`` sugar on the drill verbs: zero hits and
    ambiguity are both errors the caller reports with node counts.
    """
    found: list[Node] = [
        node
        for node in nodes
        if kind_label(node.kind) != "file"
        and node.name == name
        and (file_path is None or node.file_path == file_path)
    ]
    found.sort(key=lambda n: (n.file_path, n.start_line))
    return found


def render_human(root: str, verb: str, items: list[dict[str, Any]]) -> str:
    """Render result items as one human-readable line each."""
    lines: list[str] = [f"root: {root}  ({verb}={len(items)})"]
    for item in items:
        name: str = str(item["name"])
        kind: str = str(item["kind"])
        file_path: str = str(item["file_path"])
        span: str = f"(L{item['start_line']}-L{item['end_line']})"
        extra: str = ""
        if item.get("site_line") is not None:
            extra += f" site=L{item['site_line']}"
        if item.get("target_module") is not None:
            extra += f" -> {item['target_module']}"
        lines.append(f"{kind} {name} {span} file={file_path}{extra}")
    return "\n".join(lines)


__all__ = [
    "DEFAULT_SEARCH_LIMIT",
    "envelope",
    "exact_matches",
    "render_human",
    "search_nodes",
    "to_item",
]
