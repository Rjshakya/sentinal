"""Shared helpers over ``tree_sitter_language_pack.process``.

The pack's high-level ``process()`` API (structure + imports) is the
only tree-sitter surface this package touches: raw ``Node`` iteration
segfaults nondeterministically on Windows (py-tree-sitter 0.26), while
``process()`` is stable across thousands of parses. Parsers therefore
convert ``ProcessResult`` rows into the IR — pure Python from there.
"""

from __future__ import annotations

from tree_sitter_language_pack import ProcessConfig, ProcessResult, process

CHUNK_MAX_SIZE: int = 1000
"""Chunk size for ``process()``; chunks themselves are ignored (v1)."""


def run_process(language: str, source_text: str) -> ProcessResult:
    """Run the language pack over ``source_text`` for ``language``."""
    return process(
        source_text,
        ProcessConfig(
            language=language,
            chunk_max_size=CHUNK_MAX_SIZE,
            structure=True,
            imports=True,
            symbols=True,
        ),
    )


def one_based(line_zero_based: int) -> int:
    """Convert a pack span line (0-based) to a stored line (1-based)."""
    return line_zero_based + 1


__all__ = ["CHUNK_MAX_SIZE", "ProcessResult", "one_based", "run_process"]
