"""TypeScript / JavaScript structural parser (language pack, v1).

Covers both ``typescript`` and ``javascript`` grammars, which share
structure shapes for the extracted constructs. Definitions come from
the pack's ``structure`` rows; imports are derived from the pack's
``ImportInfo.source`` statements with pure string parsing (no raw tree
access). Bare-name call sites come from a compiled tree-sitter query
(``parser/calls.py``); callee resolution to nodes happens in the
graph builder.
"""

from __future__ import annotations

import re

from tree_sitter_language_pack import ImportInfo

from codegraph.parser._ts import one_based, run_process
from codegraph.parser.base import (
    FileAccumulator,
    ParsedFile,
    ParsedImport,
    definitions_from_structure,
)
from codegraph.parser.calls import extract_calls

TYPESCRIPT: str = "typescript"
JAVASCRIPT: str = "javascript"

_MODULE_RE: re.Pattern[str] = re.compile(r"""["']([^"']+)["']""")
"""First quoted string of an import statement is the module specifier."""


def _clause_names(clause: str) -> list[str]:
    """Extract bound names from the ``import …`` clause (pre-``from``).

    Handles default imports (``x``), named imports (``{a, b as c}``),
    namespace imports (``* as ns``), and ``x, {…}`` mixes. Best-effort:
    unrecognised shapes yield no names and the caller falls back to
    ``["*"]``.
    """
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
        # Not an ``import … from`` shape (e.g. ``export … from``).
        return []
    # Drop the trailing ``from`` keyword: the clause is what precedes it.
    head = re.sub(r"\bfrom\s*$", "", head).strip()
    names: list[str] = _clause_names(head) if head else ["*"]
    if not names:
        names = ["*"]
    return [
        ParsedImport(module=module, name=name, start_line=start_line, end_line=end_line)
        for name in names
    ]


def _imports_from_info(info: ImportInfo) -> list[ParsedImport]:
    """Convert one pack ``ImportInfo`` row into import rows."""
    if info.span is not None:
        start_line: int = one_based(info.span.start_line)
        end_line: int = max(one_based(info.span.end_line), start_line)
    else:
        start_line = 1
        end_line = 1
    return _imports_from_statement(info.source, start_line, end_line)


def _parse_with(language: str, source_text: str) -> ParsedFile:
    """Parse ``source_text`` with the ``language`` grammar."""
    total_lines: int = max(source_text.count("\n") + 1, 1)
    if not source_text.strip():
        return ParsedFile(language=language, total_lines=total_lines)
    result = run_process(language, source_text)
    acc = FileAccumulator(language=language, total_lines=total_lines)
    acc.definitions.extend(definitions_from_structure(result.structure))
    for info in result.imports:
        acc.imports.extend(_imports_from_info(info))
    acc.calls.extend(extract_calls(language, source_text.encode("utf-8")))
    return acc.build()


def parse_typescript_source(source_text: str) -> ParsedFile:
    """Parse TypeScript/TSX source text into a :class:`ParsedFile`."""
    return _parse_with(TYPESCRIPT, source_text)


def parse_javascript_source(source_text: str) -> ParsedFile:
    """Parse JavaScript/JSX source text into a :class:`ParsedFile`."""
    return _parse_with(JAVASCRIPT, source_text)


__all__ = [
    "JAVASCRIPT",
    "TYPESCRIPT",
    "parse_javascript_source",
    "parse_typescript_source",
]
