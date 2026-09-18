"""Python structural parser (tree-sitter language pack, v1).

Definitions come from the pack's ``structure`` rows; imports are
derived from the pack's ``ImportInfo.source`` statements with pure
string parsing (no raw tree access). No call resolution, no
cross-file linking.
"""

from __future__ import annotations

from tree_sitter_language_pack import ImportInfo

from codegraph.parser._ts import one_based, run_process
from codegraph.parser.base import (
    FileAccumulator,
    ParsedFile,
    ParsedImport,
    definitions_from_structure,
)

LANGUAGE: str = "python"


def _split_alias(symbol: str) -> str:
    """Return the bound name of ``a`` / ``a as b`` (alias wins)."""
    _, sep, alias = symbol.partition(" as ")
    return alias.strip() if sep else symbol.strip()


def _imports_from_statement(
    source: str, start_line: int, end_line: int
) -> list[ParsedImport]:
    """Parse one Python import statement into per-name import rows.

    Handles ``import a``, ``import a as b``, ``import x, y``,
    ``from m import a, b as c``, ``from m import *``, and relative
    ``from .[pkg] import …`` forms. Parenthesised / multi-line imports
    are normalised before splitting. Best-effort: unrecognised shapes
    yield no rows rather than wrong rows.
    """
    found: list[ParsedImport] = []
    text: str = " ".join(source.replace("(", " ").replace(")", " ").split())
    if text.startswith("from "):
        rest: str = text[5:]
        module, sep, names_part = rest.partition(" import ")
        module = module.strip()
        if not sep or not module:
            return found
        for raw in names_part.split(","):
            symbol: str = raw.strip().rstrip(";")
            if not symbol:
                continue
            if symbol == "*":
                found.append(
                    ParsedImport(
                        module=module, name="*", start_line=start_line, end_line=end_line
                    )
                )
            else:
                name: str = _split_alias(symbol)
                if name:
                    found.append(
                        ParsedImport(
                            module=module,
                            name=name,
                            start_line=start_line,
                            end_line=end_line,
                        )
                    )
    elif text.startswith("import "):
        rest = text[7:]
        for raw in rest.split(","):
            symbol = raw.strip().rstrip(";")
            if not symbol:
                continue
            # ``import a.b`` binds ``a``; ``import a.b as c`` binds ``c``.
            dotted, sep, alias = symbol.partition(" as ")
            dotted = dotted.strip()
            if not dotted:
                continue
            name = alias.strip() if sep else dotted.split(".")[0]
            if name:
                found.append(
                    ParsedImport(
                        module=dotted,
                        name=name,
                        start_line=start_line,
                        end_line=end_line,
                    )
                )
    return found


def _imports_from_info(info: ImportInfo) -> list[ParsedImport]:
    """Convert one pack ``ImportInfo`` row into import rows."""
    if info.span is not None:
        start_line: int = one_based(info.span.start_line)
        end_line: int = max(one_based(info.span.end_line), start_line)
    else:
        start_line = 1
        end_line = 1
    return _imports_from_statement(info.source, start_line, end_line)


def parse_python_source(source_text: str) -> ParsedFile:
    """Parse Python source text into a :class:`ParsedFile`."""
    total_lines: int = max(source_text.count("\n") + 1, 1)
    if not source_text.strip():
        return ParsedFile(language=LANGUAGE, total_lines=total_lines)
    result = run_process(LANGUAGE, source_text)
    acc = FileAccumulator(language=LANGUAGE, total_lines=total_lines)
    acc.definitions.extend(definitions_from_structure(result.structure))
    for info in result.imports:
        acc.imports.extend(_imports_from_info(info))
    return acc.build()


__all__ = ["LANGUAGE", "parse_python_source"]
