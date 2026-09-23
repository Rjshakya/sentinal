"""Dummy tree-sitter parse demo (native API, sexp output).

Holds three small dummy snippets inline (Python / TypeScript / Go — five
functions + one linear orchestrator + one dummy class each), parses the
selected one with the native ``tree_sitter`` ``Parser`` (via
``tree_sitter_language_pack.get_parser``, the same provider
``codegraph.parser.calls`` uses), and prints the raw S-expression.

No ``process()`` wrapper, no queries, no DB — parse one snippet, print one
tree. Runs on the calling thread: ``Parser``/``Tree``/``Node`` are not
thread-safe. Note: py-tree-sitter 0.26 dropped ``Node.sexp()``, so the
S-expression is rendered locally from named children (``(type field:
child ...)``); anonymous tokens are omitted, matching the classic shape.
"""

from __future__ import annotations

import argparse

from tree_sitter import Node, Parser, Tree
from tree_sitter_language_pack import get_parser

DUMMY_CODE_PY: str = '''\
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

DUMMY_CODE_TS: str = '''\
function fetchData(): number[] {
  return [1, 2, 3];
}

function cleanData(data: number[]): number[] {
  return data.filter((x) => x > 0);
}

function analyzeData(data: number[]): number {
  return data.reduce((acc, x) => acc + x, 0);
}

function formatReport(total: number): string {
  return `total: ${total}`;
}

function saveReport(text: string): void {
  console.log(text);
}

function runPipeline(): void {
  const data = fetchData();
  const cleaned = cleanData(data);
  const total = analyzeData(cleaned);
  const text = formatReport(total);
  saveReport(text);
}

class ReportBuilder {
  private sections: string[] = [];

  addSection(section: string): void {
    this.sections.push(section);
  }

  build(): string {
    return this.sections.join("\\n");
  }
}
'''

DUMMY_CODE_GO: str = '''\
package main

import (
  "fmt"
  "strings"
)

func fetchData() []int {
  return []int{1, 2, 3}
}

func cleanData(data []int) []int {
  var out []int
  for _, x := range data {
    if x > 0 {
      out = append(out, x)
    }
  }
  return out
}

func analyzeData(data []int) int {
  total := 0
  for _, x := range data {
    total += x
  }
  return total
}

func formatReport(total int) string {
  return fmt.Sprintf("total: %d", total)
}

func saveReport(text string) {
  fmt.Println(text)
}

func runPipeline() {
  data := fetchData()
  cleaned := cleanData(data)
  total := analyzeData(cleaned)
  text := formatReport(total)
  saveReport(text)
}

type ReportBuilder struct {
  sections []string
}

func (r *ReportBuilder) AddSection(section string) {
  r.sections = append(r.sections, section)
}

func (r *ReportBuilder) Build() string {
  return strings.Join(r.sections, "\\n")
}
'''

_LANG_MAP: dict[str, tuple[str, str]] = {
    "py": ("python", DUMMY_CODE_PY),
    "ts": ("typescript", DUMMY_CODE_TS),
    "go": ("go", DUMMY_CODE_GO),
}


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
    """Parse the selected dummy snippet natively and print its S-expression."""
    arg_parser = argparse.ArgumentParser(description=__doc__)
    arg_parser.add_argument(
        "--lang",
        "-l",
        choices=sorted(_LANG_MAP),
        default="py",
        help="dummy snippet language: py | ts | go (default: py)",
    )
    args = arg_parser.parse_args()
    language, code = _LANG_MAP[args.lang]
    parser: Parser = get_parser(language)
    tree: Tree = parser.parse(code.encode("utf-8"))
    print(_sexp(tree.root_node))


if __name__ == "__main__":
    main()
