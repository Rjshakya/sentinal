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

    module: str  # raw module specifier, e.g. "os" | "pkg.utils" | ".sibling"
    name: str  # bound symbol in the importing file, or "*" for star imports
    start_line: int  # 1-based
    end_line: int  # 1-based
    original: str = ""  # name in the defining module; "" means same as ``name``
    # ``from utils import helper as h`` -> name="h", original="helper".
    # ``from utils import helper`` -> name="helper", original="".
    # ``import os`` -> name="os", original="".

    @property
    def effective_original(self) -> str:
        """Return the defining-module name (falls back to the bound name)."""
        return self.original or self.name


@dataclass(frozen=True, slots=True)
class ParsedCall:
    """A bare-name call site: ``caller`` calls ``callee``.

    ``caller`` is the innermost enclosing named definition; module-level
    call sites are dropped, so ``caller`` is never empty. ``callee`` is
    the called bare name — resolution to a node happens in the link
    phase, which drops names that resolve to nothing indexed.
    """

    caller: str
    callee: str
    site_line: int | None = None  # 1-based call-site line (None = unknown)


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
