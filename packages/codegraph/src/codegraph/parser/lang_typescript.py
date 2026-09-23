"""TypeScript / JavaScript structural extraction from a raw tree.

Pure: takes the parsed ``root``, returns defs + imports. Covers both the
``typescript`` and ``javascript`` grammars, which share structure shapes.
"""

from __future__ import annotations

import re

from tree_sitter import Node

from codegraph.parser.base import ParsedDefinition, ParsedImport
from codegraph.parser.raw_core import field_text, node_text, span, walk

TYPESCRIPT: str = "typescript"
JAVASCRIPT: str = "javascript"

_MODULE_RE: re.Pattern[str] = re.compile(r"""["']([^"']+)["']""")


def _clause_names(clause: str) -> list[str]:
    """Extract bound names from the ``import …`` clause (pre-``from``)."""
    names: list[str] = []
    text: str = clause.strip()
    if text.startswith("type "):
        text = text[5:].strip()
    if not text:
        return names
    if text.startswith("{"):
        inner: str = text[1:]
        if "}" in inner:
            inner = inner[: inner.index("}")]
        for raw in inner.split(","):
            symbol: str = raw.strip()
            if not symbol or symbol.startswith("//"):
                continue
            _, sep, alias = symbol.partition(" as ")
            names.append(alias.strip() if sep else symbol)
    elif text.startswith("*"):
        _, sep, alias = text.partition(" as ")
        names.append(alias.strip() if sep else "*")
    else:
        head, sep, tail = text.partition(",")
        default: str = head.strip()
        if default and default not in ("*", "{"):
            names.append(default)
        if sep and tail.strip():
            names.extend(_clause_names(tail.strip()))
    return [name for name in names if name]


def _imports_from_statement(
    source: str, start_line: int, end_line: int
) -> list[ParsedImport]:
    """Parse one TS/JS import statement into per-name import rows."""
    match: re.Match[str] | None = _MODULE_RE.search(source)
    if match is None:
        return []
    module: str = match.group(1).strip()
    if not module:
        return []
    head: str = source[: match.start()].strip()
    if head.startswith("import"):
        head = head[6:].strip()
    else:
        return []
    head = re.sub(r"\bfrom\s*$", "", head).strip()
    names: list[str] = _clause_names(head) if head else ["*"]
    if not names:
        names = ["*"]
    return [
        ParsedImport(module=module, name=name, start_line=start_line, end_line=end_line)
        for name in names
    ]


def extract_imports(root: Node) -> list[ParsedImport]:
    """Collect imports from ``import_statement`` nodes."""
    found: list[ParsedImport] = []
    for node in walk(root):
        if node.type != "import_statement":
            continue
        text: str = node_text(node)
        if not text.strip().startswith("import"):
            continue
        start, end = span(node)
        found.extend(_imports_from_statement(text, start, end))
    return found


def _bound_variable_name(node: Node) -> str:
    """Return the variable name binding an arrow/function expression."""
    parent: Node | None = node.parent
    if parent is not None and parent.type == "variable_declarator":
        return field_text(parent, "name")
    return ""


def extract_definitions(root: Node) -> list[ParsedDefinition]:
    """Collect classes, functions, methods, and arrow-bound consts (preorder)."""
    found: list[ParsedDefinition] = []
    scope: list[tuple[str, str]] = []  # enclosing (kind, name)
    stack: list[tuple[Node, bool]] = [(root, False)]  # True = exit, pops scope
    while stack:
        node, exiting = stack.pop()
        if exiting:
            scope.pop()
            continue
        if node.type == "class_declaration":
            kind: str = "class"
            name: str = field_text(node, "name")
        elif node.type == "function_declaration":
            kind = "method" if scope and scope[-1][0] == "class" else "function"
            name = field_text(node, "name")
        elif node.type == "method_definition":
            kind = "method"
            name = field_text(node, "name")
        elif node.type in ("arrow_function", "function_expression"):
            kind = "function"
            name = _bound_variable_name(node)
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
                parent=scope[-1][1] if scope else None,
            )
        )
        scope.append(("class" if kind == "class" else "function", name))
        stack.append((node, True))
        for child in reversed(node.named_children):
            stack.append((child, False))
    return found


__all__ = ["JAVASCRIPT", "TYPESCRIPT", "extract_definitions", "extract_imports"]
