"""Go structural extraction from a raw tree-sitter tree.

Pure: takes the parsed ``root``, returns defs + imports. Struct types
map to ``class`` nodes; functions and methods keep their Go names.
"""

from __future__ import annotations

from tree_sitter import Node

from codegraph.parser.base import ParsedDefinition, ParsedImport
from codegraph.parser.raw_core import field_text, node_text, span, walk

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


__all__ = ["LANGUAGE", "extract_definitions", "extract_imports"]
