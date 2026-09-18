"""Shared intermediate representation for the language parsers.

Each parser turns source text into a :class:`ParsedFile` — flat lists
of definitions and imports with 1-based line spans. The ``graph``
builder (``parser/__init__.py``) then converts the IR into ``Node``
/ ``Edge`` rows, so parsers never touch the database layer.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from tree_sitter_language_pack import StructureItem


@dataclass(frozen=True, slots=True)
class ParsedDefinition:
    """A class or function found in a source file."""

    kind: str  # "class" | "function"
    name: str
    start_line: int  # 1-based, inclusive
    end_line: int  # 1-based, inclusive
    parent: str | None = None  # nearest enclosing def name (any kind)
    is_method: bool = False  # function directly enclosed by a class


@dataclass(frozen=True, slots=True)
class ParsedImport:
    """A single imported name (one row per name, not per statement)."""

    module: str  # raw module specifier, e.g. "os" | "./utils"
    name: str  # imported symbol, or "*" / module for bare imports
    start_line: int  # 1-based
    end_line: int  # 1-based


@dataclass(frozen=True, slots=True)
class ParsedFile:
    """Parser output for one source file."""

    language: str
    definitions: tuple[ParsedDefinition, ...] = ()
    imports: tuple[ParsedImport, ...] = ()
    total_lines: int = 1
    has_error: bool = False


def empty_file(language: str, total_lines: int = 1) -> ParsedFile:
    """Return an empty :class:`ParsedFile` (unparseable or blank source)."""
    return ParsedFile(
        language=language,
        definitions=(),
        imports=(),
        total_lines=max(total_lines, 1),
        has_error=True,
    )


@dataclass(slots=True)
class FileAccumulator:
    """Mutable builder collected during a tree walk."""

    language: str
    total_lines: int = 1
    has_error: bool = False
    definitions: list[ParsedDefinition] = field(default_factory=list)
    imports: list[ParsedImport] = field(default_factory=list)

    def build(self) -> ParsedFile:
        """Freeze the accumulator into a :class:`ParsedFile`."""
        return ParsedFile(
            language=self.language,
            definitions=tuple(self.definitions),
            imports=tuple(self.imports),
            total_lines=max(self.total_lines, 1),
            has_error=self.has_error,
        )


CLASS_KINDS: frozenset[str] = frozenset({"class", "interface", "enum", "struct"})
"""Structure kinds recorded as ``class`` nodes (``str(kind).lower()``)."""

FUNCTION_KINDS: frozenset[str] = frozenset({"function", "method"})
"""Structure kinds recorded as ``function`` nodes."""


def definitions_from_structure(
    items: Sequence[StructureItem],
    enclosing: tuple[str | None, bool] = (None, False),
) -> list[ParsedDefinition]:
    """Convert pack ``StructureItem`` rows into :class:`ParsedDefinition`.

    ``enclosing`` is ``(name, is_class)`` of the nearest enclosing
    definition: ``parent`` always records the enclosing name (the
    caller side of the caller/callee relation), while ``is_method`` is
    set only when a function is directly enclosed by a class. Closures
    keep their enclosing function as parent. Items whose name is empty
    or whose kind is outside the v1 sets are skipped (descending into
    their children with the enclosing scope unchanged).
    """
    from codegraph.parser._ts import one_based

    found: list[ParsedDefinition] = []
    stack: list[tuple[StructureItem, tuple[str | None, bool]]] = [
        (item, enclosing) for item in reversed(items)
    ]
    while stack:
        item, (enclosing_name, enclosing_is_class) = stack.pop()
        kind: str = str(item.kind).lower()
        name: str = item.name or ""
        if item.span is not None:
            start_line: int = one_based(item.span.start_line)
            end_line: int = one_based(item.span.end_line)
        else:
            start_line = 1
            end_line = 1
        end_line = max(end_line, start_line)
        if kind in CLASS_KINDS and name:
            found.append(
                ParsedDefinition(
                    kind="class",
                    name=name,
                    start_line=start_line,
                    end_line=end_line,
                    parent=enclosing_name,
                    is_method=False,
                )
            )
            stack.extend(
                (child, (name, True)) for child in reversed(item.children)
            )
        elif kind in FUNCTION_KINDS and name:
            is_method: bool = enclosing_is_class
            found.append(
                ParsedDefinition(
                    kind="function",
                    name=name,
                    start_line=start_line,
                    end_line=end_line,
                    parent=enclosing_name,
                    is_method=is_method,
                )
            )
            stack.extend(
                (child, (name, False)) for child in reversed(item.children)
            )
        else:
            stack.extend(
                (child, (enclosing_name, enclosing_is_class))
                for child in reversed(item.children)
            )
    return found


__all__ = [
    "CLASS_KINDS",
    "FUNCTION_KINDS",
    "FileAccumulator",
    "ParsedDefinition",
    "ParsedFile",
    "ParsedImport",
    "definitions_from_structure",
    "empty_file",
]
