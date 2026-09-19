"""Call-site extraction via compiled tree-sitter queries (Option A).

This is the only raw tree-sitter surface in the package besides
``process()``: ``get_parser`` + ``parse`` + ``Query``/``QueryCursor``
captures + upward ``.parent`` hops. There is deliberately no recursive
descent — queries run in C and return only captures, and caller
resolution climbs parents (a few FFI crossings per call site), which
keeps the native surface far below the recursive-walk pattern that
segfaulted on Windows. Like every other parse step, this runs on the
event-loop thread: ``Parser`` / ``Tree`` / ``Node`` are not
thread-safe.

Only bare-name calls (``name(…)``) are captured, via
``(identifier)`` as the call's function field — attribute calls
(``obj.method(…)``, ``self.x(…)``) never match by construction. The
caller is the innermost enclosing *named* definition; anonymous
scopes (arrow callbacks, bare function expressions) are climbed past
so their calls attribute to the enclosing named function.
Module-level call sites have no enclosing definition and are dropped.
"""

from __future__ import annotations

from tree_sitter import Node, Query, QueryCursor
from tree_sitter_language_pack import get_parser

from codegraph.parser.base import ParsedCall

_CALL_QUERIES: dict[str, str] = {
    "python": "(call function: (identifier) @callee)",
    "typescript": "(call_expression function: (identifier) @callee)",
    "javascript": "(call_expression function: (identifier) @callee)",
}
"""Per-language call query; the ``@callee`` capture is a bare identifier."""

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
}
"""Node types that own a call site's enclosing scope, per language."""


def _node_text(node: Node) -> str:
    """Decode a node's source text (empty when the node has none)."""
    raw: bytes | None = node.text
    if raw is None:
        return ""
    return raw.decode("utf-8", errors="ignore")


def _scope_name(scope: Node) -> str | None:
    """Return a scope node's declared name, if it has one.

    Covers ``def f`` / ``function f`` (the ``name`` field) and
    anonymous functions bound to a variable (``const f = () => …``,
    ``f = function …`` — the enclosing declarator / assignment target
    names the scope). Returns ``None`` for genuinely anonymous scopes.
    """
    name_node: Node | None = scope.child_by_field_name("name")
    if name_node is not None:
        name: str = _node_text(name_node)
        if name:
            return name
    if scope.type in ("arrow_function", "function_expression"):
        parent: Node | None = scope.parent
        if parent is not None and parent.type == "variable_declarator":
            bound: Node | None = parent.child_by_field_name("name")
            if bound is not None:
                bound_name: str = _node_text(bound)
                if bound_name:
                    return bound_name
        if parent is not None and parent.type == "assignment_expression":
            target: Node | None = parent.child_by_field_name("left")
            if target is not None:
                target_name: str = _node_text(target)
                if target_name.isidentifier():
                    return target_name
    return None


def _enclosing_caller(start: Node | None, scopes: frozenset[str]) -> str | None:
    """Walk up to the innermost enclosing *named* scope.

    Anonymous scopes (arrows, bare function expressions) carry no
    ``name`` field and are climbed past; the first scope with a name
    wins. Returns ``None`` for module-level call sites.
    """
    probe: Node | None = start
    while probe is not None:
        if probe.type in scopes:
            name: str | None = _scope_name(probe)
            if name is not None:
                return name
        probe = probe.parent
    return None


def extract_calls(language: str, source: bytes) -> list[ParsedCall]:
    """Extract bare-name call sites from ``source`` for ``language``.

    Returns one :class:`ParsedCall` per call site whose caller could
    be named. Unknown languages yield no calls; callee resolution
    (imports, same-file defs, builtins) happens in the graph builder.
    """
    query_src: str | None = _CALL_QUERIES.get(language)
    scopes: frozenset[str] | None = _SCOPE_TYPES.get(language)
    if query_src is None or scopes is None:
        return []
    parser = get_parser(language)
    grammar = parser.language
    assert grammar is not None  # get_parser always binds a language
    root: Node = parser.parse(source).root_node
    query = Query(grammar, query_src)
    captures: dict[str, list[Node]] = QueryCursor(query).captures(root)
    found: list[ParsedCall] = []
    for node in captures.get("callee", []):
        callee: str = _node_text(node)
        if not callee:
            continue
        caller: str | None = _enclosing_caller(node.parent, scopes)
        if caller is None:
            continue
        found.append(ParsedCall(caller=caller, callee=callee))
    return found


__all__ = ["extract_calls"]
