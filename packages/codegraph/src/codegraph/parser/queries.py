"""Bare-name call-site extraction via compiled tree-sitter queries.

The only query surface in the package: each query captures a bare
``(identifier)`` in call-function position. Attribute calls
(``obj.method()``, ``self.x()``, ``pkg.Fn()``) never match by
construction. The caller is the innermost enclosing named definition;
module-level call sites are dropped. All functions are pure given the
already-parsed tree.
"""

from __future__ import annotations

from tree_sitter import Language, Node, Query, QueryCursor
from tree_sitter_language_pack import get_parser

from codegraph.parser.base import ParsedCall
from codegraph.parser.raw_core import field_text, node_text

_CALL_QUERIES: dict[str, str] = {
    "python": "(call function: (identifier) @callee)",
    "typescript": "(call_expression function: (identifier) @callee)",
    "javascript": "(call_expression function: (identifier) @callee)",
    "go": "(call_expression function: (identifier) @callee)",
}

_SCOPE_TYPES: dict[str, frozenset[str]] = {
    "python": frozenset({"function_definition"}),
    "typescript": frozenset(
        {
            "function_declaration",
            "function_expression",
            "arrow_function",
            "method_definition",
        }
    ),
    "javascript": frozenset(
        {
            "function_declaration",
            "function_expression",
            "arrow_function",
            "method_definition",
        }
    ),
    "go": frozenset({"function_declaration", "method_declaration"}),
}


def _scope_name(scope: Node) -> str | None:
    """Return a scope node's declared name, if it has one."""
    name: str = field_text(scope, "name")
    if name:
        return name
    if scope.type in ("arrow_function", "function_expression"):
        parent: Node | None = scope.parent
        if parent is not None and parent.type == "variable_declarator":
            bound: str = field_text(parent, "name")
            if bound:
                return bound
        if parent is not None and parent.type == "assignment_expression":
            target: Node | None = parent.child_by_field_name("left")
            if target is not None:
                text: str = node_text(target)
                if text.isidentifier():
                    return text
    if scope.type == "method_declaration":
        # Go: name is a field_identifier, not identifier.
        name_node: Node | None = scope.child_by_field_name("name")
        if name_node is not None:
            text = node_text(name_node)
            if text:
                return text
    return None


def _enclosing_caller(start: Node | None, scopes: frozenset[str]) -> str | None:
    """Walk up to the innermost enclosing named scope."""
    probe: Node | None = start
    while probe is not None:
        if probe.type in scopes:
            name: str | None = _scope_name(probe)
            if name is not None:
                return name
        probe = probe.parent
    return None


def extract_calls(language: str, root: Node, grammar: Language) -> list[ParsedCall]:
    """Extract bare-name call sites from an already-parsed ``root``."""
    query_src: str | None = _CALL_QUERIES.get(language)
    scopes: frozenset[str] | None = _SCOPE_TYPES.get(language)
    if query_src is None or scopes is None:
        return []
    query = Query(grammar, query_src)
    captures: dict[str, list[Node]] = QueryCursor(query).captures(root)
    found: list[ParsedCall] = []
    for node in captures.get("callee", []):
        callee: str = node_text(node)
        if not callee:
            continue
        caller: str | None = _enclosing_caller(node.parent, scopes)
        if caller is None:
            continue
        found.append(ParsedCall(caller=caller, callee=callee))
    return found


def grammar_of(language: str) -> Language:
    """Return the compiled grammar for ``language`` (for query binding)."""
    grammar: Language | None = get_parser(language).language
    assert grammar is not None
    return grammar


__all__ = ["extract_calls", "grammar_of"]
