"""Shared intermediate representation for the raw parsers.

Each language extractor turns a tree-sitter tree into a :class:`ParsedFile`
— flat lists of definitions, imports, and call sites with 1-based line
spans. The graph builder (``parser/__init__.py``) then converts the IR
into ``Node`` / ``Edge`` rows, so parsers never touch the database layer.
All IR constructors are pure.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class ParsedDefinition:
    """A class, function, or method found in a source file."""

    kind: str  # "class" | "function" | "method"
    name: str
    start_line: int  # 1-based, inclusive
    end_line: int  # 1-based, inclusive
    parent: str | None = None  # nearest enclosing def name (any kind)


@dataclass(frozen=True, slots=True)
class ParsedImport:
    """A single imported name (one row per name, not per statement)."""

    module: str  # raw module specifier, e.g. "os" | "./utils" | "fmt"
    name: str  # imported symbol, or "*" / module for bare imports
    start_line: int  # 1-based
    end_line: int  # 1-based


@dataclass(frozen=True, slots=True)
class ParsedCall:
    """A bare-name call site: ``caller`` calls ``callee``.

    ``caller`` is the innermost enclosing named definition; module-level
    call sites are dropped, so ``caller`` is never empty. ``callee`` is
    the called bare name — resolution to a node happens in the graph
    builder, which skips names that resolve to nothing indexed.
    """

    caller: str
    callee: str


@dataclass(frozen=True, slots=True)
class ParsedFile:
    """Parser output for one source file."""

    language: str
    definitions: tuple[ParsedDefinition, ...] = ()
    imports: tuple[ParsedImport, ...] = ()
    calls: tuple[ParsedCall, ...] = ()
    total_lines: int = 1
    has_error: bool = False


def empty_file(language: str, total_lines: int = 1) -> ParsedFile:
    """Return an empty :class:`ParsedFile` (unparseable or blank source)."""
    return ParsedFile(
        language=language,
        definitions=(),
        imports=(),
        calls=(),
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
    calls: list[ParsedCall] = field(default_factory=list)

    def build(self) -> ParsedFile:
        """Freeze the accumulator into a :class:`ParsedFile`."""
        return ParsedFile(
            language=self.language,
            definitions=tuple(self.definitions),
            imports=tuple(self.imports),
            calls=tuple(self.calls),
            total_lines=max(self.total_lines, 1),
            has_error=self.has_error,
        )


__all__ = [
    "FileAccumulator",
    "ParsedCall",
    "ParsedDefinition",
    "ParsedFile",
    "ParsedImport",
    "empty_file",
]
