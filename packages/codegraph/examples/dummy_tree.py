"""Dummy tree-sitter parse demo (native API, sexp output).

Holds a small dummy Python snippet inline (five functions + one linear
orchestrator + one dummy class), parses it with the native ``tree_sitter``
``Parser`` (via ``tree_sitter_language_pack.get_parser``, the same provider
``codegraph.parser.calls`` uses), and prints the raw S-expression.

No ``process()`` wrapper, no queries, no DB — parse one snippet, print one
tree. Runs on the calling thread: ``Parser``/``Tree``/``Node`` are not
thread-safe. Note: py-tree-sitter 0.26 dropped ``Node.sexp()``, so the
S-expression is rendered locally from named children (``(type field:
child ...)``); anonymous tokens are omitted, matching the classic shape.
"""

from __future__ import annotations

from tree_sitter import Node, Parser, Tree
from tree_sitter_language_pack import get_parser

DUMMY_CODE: str = '''\
def fetch_data() -> list[int]:
    return [1, 2, 3]


def clean_data(data: list[int]) -> list[int]:
    return [x for x in data if x > 0]


def analyze_data(data: list[int]) -> int:
    return sum(data)


def format_report(total: int) -> str:
    return f"total: {total}"


def save_report(text: str) -> None:
    print(text)


def run_pipeline() -> None:
    data = fetch_data()
    cleaned = clean_data(data)
    total = analyze_data(cleaned)
    text = format_report(total)
    save_report(text)


class ReportBuilder:
    def __init__(self) -> None:
        self.sections: list[str] = []

    def add_section(self, section: str) -> None:
        self.sections.append(section)

    def build(self) -> str:
        return "\\n".join(self.sections)
'''


def _sexp(node: Node) -> str:
    """Render ``node``'s subtree as an S-expression string."""
    if node.named_child_count == 0:
        return f"({node.type})"
    parts: list[str] = []
    for index, child in enumerate(node.named_children):
        field: str | None = node.field_name_for_named_child(index)
        rendered: str = _sexp(child)
        parts.append(f"{field}: {rendered}" if field else rendered)
    return f"({node.type} {' '.join(parts)})"


def main() -> None:
    """Parse ``DUMMY_CODE`` natively and print its S-expression."""
    parser: Parser = get_parser("python")
    tree: Tree = parser.parse(DUMMY_CODE.encode("utf-8"))
    print(_sexp(tree.root_node))


if __name__ == "__main__":
    main()
