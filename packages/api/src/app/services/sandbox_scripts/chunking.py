"""Tree-sitter chunker.

Used inside the indexing sandbox. Walks a cloned repo, parses each
recognized source file with ``tree_sitter_language_pack.process()``,
and returns a flat list of chunks (one dict per chunk).

This is part of the Sentinel in-sandbox indexing flow and is uploaded
to each sandbox at runtime by ``app.services.indexing``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterator

from pydantic import BaseModel, RootModel
from tree_sitter_language_pack import ProcessConfig, has_language, process

LANGUAGE_MAP: dict[str, str] = {
    ".py": "python",
    ".ts": "typescript",
    ".tsx": "tsx",
    ".js": "javascript",
    ".jsx": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
    ".kt": "kotlin",
    ".swift": "swift",
}

IGNORE_DIRS: set[str] = {
    "node_modules",
    "dist",
    "build",
    ".next",
    "target",
    ".venv",
    "vendor",
    ".git",
    "__pycache__",
    ".cache",
    ".pytest_cache",
    ".mypy_cache",
    ".tox",
    "coverage",
    ".turbo",
    ".svelte-kit",
    ".gradle",
    ".idea",
    ".vscode",
}


class FileChunk(BaseModel):
    file_name: str
    content: str
    start_line: int
    end_line: int
    language: str
    # node_types: Any
    size_bytes: int


class ChunkedRepo(RootModel[dict[str, list[FileChunk]]]):
    root: dict[str, list[FileChunk]]


def _should_skip(path: Path) -> bool:
    return any(part in IGNORE_DIRS for part in path.parts)


def _iter_repo_files(repo_path: str) -> Iterator[Path]:
    root = Path(repo_path)
    if not root.exists():
        raise FileNotFoundError(f"Repo path does not exist: {repo_path}")
    for file_path in sorted(root.rglob("*")):
        if not file_path.is_file():
            continue
        if _should_skip(file_path):
            continue
        yield file_path


def chunk_repo(*, repo_path: str, chunk_size: int = 800) -> ChunkedRepo:
    """Walk ``repo_path`` and return ChunkedRepo.

    Each FileChunk:
      - content:     str
      - start_line:  int
      - end_line:    int
      - language:    str
      - node_types:  list[str]
      - size_bytes:  int
    """
    chunks = ChunkedRepo(root={})
    for file_path in _iter_repo_files(repo_path):
        ext = file_path.suffix
        language = LANGUAGE_MAP.get(ext)
        if not language or not has_language(language):
            continue
        try:
            source = file_path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        result = process(
            source,
            ProcessConfig(
                language=language,
                chunk_max_size=chunk_size,
                structure=True,
                imports=True,
                docstrings=True,
            ),
        )

        for chunk in result.chunks:
            chunks.root.setdefault(str(file_path), []).append(
                FileChunk(
                    file_name=str(file_path),
                    content=chunk.content,
                    start_line=chunk.start_line,
                    end_line=chunk.end_line,
                    language=language,
                    size_bytes=chunk.end_byte - chunk.start_byte,
                    # node_types=chunk.node_types,  # pyright: ignore[reportAttributeAccessIssue]
                )
            )
    return chunks
