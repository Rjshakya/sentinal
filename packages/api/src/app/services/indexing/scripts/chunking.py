"""In-sandbox chunking module.

Uploaded as-is into the indexing sandbox by ``uploadScriptsToSandbox`` and
imported by ``ingestion.py`` (a sibling file in the same sandbox
directory). The host never imports this file — it reads it as bytes and
ships it via ``sandbox.fs_write``.

The public surface is :func:`iter_chunks`, a generator that yields
batches (lists) of :class:`Chunk` rows. Yield semantics:

- yield when the running buffer reaches ``batch_size`` (mid-file is OK);
- yield when a file finishes with a non-empty buffer (file-complete);
- yield the trailing partial batch (if any) when the walk ends.

``tree_sitter_language_pack`` is imported at the top of this file because
the sandbox template bakes it in. Pyright on the host will report the
dep as missing; that is expected and silenced.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

from pydantic import BaseModel
from tree_sitter_language_pack import (  # type: ignore[reportMissingImports]
    ProcessConfig,
    has_language,
    process,
)

LANGUAGE_MAP: dict[str, str] = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".rs": "rust",
    ".go": "go",
    ".java": "java",
    ".rb": "ruby",
    ".ex": "elixir",
    ".exs": "elixir",
    ".php": "php",
    ".cs": "csharp",
    ".cpp": "cpp",
    ".cc": "cpp",
    ".h": "c",
    ".hpp": "cpp",
    ".c": "c",
    ".swift": "swift",
    ".kt": "kotlin",
    ".kts": "kotlin",
    ".sh": "bash",
    ".bash": "bash",
    ".zsh": "bash",
    ".html": "html",
    ".css": "css",
    ".scss": "scss",
    ".md": "markdown",
    ".json": "json",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".toml": "toml",
    ".sql": "sql",
    ".vue": "vue",
    ".dockerfile": "dockerfile",
}

SKIP_DIRS: set[str] = {
    ".git",
    ".github",
    ".idea",
    ".vscode",
    ".next",
    "__pycache__",
    "build",
    "dist",
    "node_modules",
    "target",
    "venv",
    ".venv",
}

MAX_FILE_BYTES: int = 20 * 1024 * 1024
"""Skip files larger than this — tree-sitter chunking is for source."""

DEFAULT_BATCH_SIZE: int = 60
"""Batch size the generator yields at (overridable per call)."""

DEFAULT_CHUNK_MAX_SIZE: int = 1000
"""Upper bound (bytes) for syntax-aware code chunks."""

EMBEDDING_SOURCE_COLUMN: str = "content"


class Chunk(BaseModel):
    """One syntax-aware code chunk as emitted by the chunking generator."""

    file_name: str
    language: str
    start_line: int
    end_line: int
    node_types: list[str] = []
    size_bytes: int
    content: str


def iter_supported_files(
    repo_dir: str,
) -> Iterator[tuple[Path, str, str, Path]]:
    """Yield supported-language files under ``repo_dir``.

    Skips directories in :data:`SKIP_DIRS` and files whose extension is
    not in :data:`LANGUAGE_MAP` (or whose language is not in the
    bundled tree-sitter registry). Silently skips files larger than
    :data:`MAX_FILE_BYTES` and files that fail to decode.

    Yields 4-tuples ``(filepath, language, source, repo_root)`` so the
    caller can decode the file just once and chunk it in place.
    """
    root = Path(repo_dir)
    for parent, dirs, filenames in os.walk(repo_dir):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for filename in sorted(filenames):
            ext = Path(filename).suffix
            language = LANGUAGE_MAP.get(ext)
            if language is None or not has_language(language):
                continue
            filepath = os.path.join(parent, filename)
            try:
                if os.path.getsize(filepath) > MAX_FILE_BYTES:
                    continue
                source = Path(filepath).read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            if not source.strip():
                continue
            yield Path(filepath), language, source, root


def chunk_one_file(
    filepath: Path,
    language: str,
    source: str,
    root: Path,
) -> Iterator[Chunk]:
    """Yield :class:`Chunk` rows for a single supported file."""
    rel_path = str(filepath.relative_to(root)).replace(os.sep, "/")
    result = process(
        source,
        ProcessConfig(
            language=language,
            chunk_max_size=DEFAULT_CHUNK_MAX_SIZE,
            structure=True,
            imports=True,
            docstrings=True,
        ),
    )
    for chunk in result.chunks:
        md = getattr(chunk, "metadata", None)
        node_types = getattr(md, "node_types", None)
        if node_types is None:
            node_types = getattr(chunk, "node_types", None)
        yield Chunk(
            file_name=rel_path,
            language=language,
            start_line=chunk.start_line,
            end_line=chunk.end_line,
            node_types=list(node_types or []),
            size_bytes=chunk.end_byte - chunk.start_byte,
            content=chunk.content,
        )


def iter_chunks(
    repo_dir: str,
    *,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> Iterator[list[Chunk]]:
    """Walk ``repo_dir`` and yield batches of :class:`Chunk` rows.

    A batch is yielded when **either**:

    - the running buffer reaches ``batch_size`` items (mid-file), or
    - a file finishes with a non-empty buffer (file-complete boundary).

    A trailing non-empty buffer is always yielded at the end of the
    walk.
    """

    buffer: list[Chunk] = []

    for filepath, language, source, root in iter_supported_files(repo_dir):
        for chunk in chunk_one_file(filepath, language, source, root):
            buffer.append(chunk)
            if len(buffer) >= batch_size:
                yield buffer
                buffer = []

        if buffer:
            yield buffer
            buffer = []

    if buffer:
        yield buffer
