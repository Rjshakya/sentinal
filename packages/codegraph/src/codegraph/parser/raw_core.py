"""Raw tree-sitter surface for the v2 pipeline.

Thin wrapper over ``tree_sitter_language_pack.get_parser`` + ``parse``.
Parsing runs on the calling thread: ``Parser`` / ``Tree`` / ``Node``
are not thread-safe. Walk helpers are pure and iterative — no recursion,
no queries here (queries live in ``queries.py``).
"""

from __future__ import annotations

from collections.abc import Iterator

from tree_sitter import Node, Parser, Tree
from tree_sitter_language_pack import get_parser


def parse(language: str, source: bytes) -> Tree:
    """Parse ``source`` with the ``language`` grammar on this thread."""
    parser: Parser = get_parser(language)
    return parser.parse(source)


def node_text(node: Node) -> str:
    """Decode a node's source text (empty when the node has none)."""
    raw: bytes | None = node.text
    if raw is None:
        return ""
    return raw.decode("utf-8", errors="ignore")


def field_text(node: Node, field: str) -> str:
    """Decode a named field's text (empty when absent)."""
    child: Node | None = node.child_by_field_name(field)
    if child is None:
        return ""
    return node_text(child)


def span(node: Node) -> tuple[int, int]:
    """Return a node's 1-based ``(start_line, end_line)`` span."""
    start: int = node.start_point[0] + 1
    end: int = node.end_point[0] + 1
    return (start, max(end, start))


def has_error(root: Node) -> bool:
    """Return True when the tree contains an error node."""
    stack: list[Node] = [root]
    while stack:
        node: Node = stack.pop()
        if node.type == "ERROR" or node.is_missing:
            return True
        stack.extend(node.named_children)
    return False


def walk(root: Node) -> Iterator[Node]:
    """Yield every named node in the tree, depth-first (iterative)."""
    stack: list[Node] = [root]
    while stack:
        node: Node = stack.pop()
        yield node
        stack.extend(reversed(node.named_children))


__all__ = ["field_text", "has_error", "node_text", "parse", "span", "walk"]
