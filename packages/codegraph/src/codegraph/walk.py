"""File discovery for the CLI.

Maps extensions to tree-sitter language names, prunes noise
directories, and skips oversized / undecodable / empty files — the same
spirit as the API's ``chunking.py`` walker, but scoped to the v1
language set (Python + TypeScript/JavaScript).
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from pathlib import Path

EXT_TO_LANGUAGE: dict[str, str] = {
    ".py": "python",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".js": "javascript",
    ".jsx": "javascript",
}

SKIP_DIRS: frozenset[str] = frozenset(
    {
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
)

MAX_FILE_BYTES: int = 20 * 1024 * 1024
"""Skip files larger than this — the graph is for source, not dumps."""


@dataclass(frozen=True, slots=True)
class DiscoveredFile:
    """A supported source file found under the scan root."""

    abs_path: Path
    rel_path: str
    language: str


def normalise_root(path: Path) -> Path:
    """Return the resolved absolute scan root."""
    return path.expanduser().resolve()


def to_rel_posix(abs_path: Path, root: Path) -> str:
    """Return the ``/``-separated path of ``abs_path`` relative to ``root``."""
    return abs_path.relative_to(root).as_posix()


def discover_files(target: Path, root: Path) -> list[DiscoveredFile]:
    """List supported files for ``target`` (file or dir) under ``root``.

    Directory walks are pruned at ``SKIP_DIRS`` and sorted for stable
    output. Files that are unsupported, oversized, or empty are skipped.
    """
    candidates: list[Path] = []
    if target.is_file():
        candidates = [target]
    else:
        for parent, dirs, filenames in os.walk(target):
            dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
            for filename in sorted(filenames):
                candidates.append(Path(parent) / filename)

    found: list[DiscoveredFile] = []
    for abs_path in candidates:
        language: str | None = EXT_TO_LANGUAGE.get(abs_path.suffix.lower())
        if language is None:
            continue
        try:
            if abs_path.stat().st_size > MAX_FILE_BYTES:
                continue
        except OSError:
            continue
        try:
            if not abs_path.is_relative_to(root):
                continue
            rel: str = to_rel_posix(abs_path.resolve(), root)
        except (OSError, ValueError):
            continue
        found.append(
            DiscoveredFile(abs_path=abs_path, rel_path=rel, language=language)
        )
    return found


async def adiscover_files(target: Path, root: Path) -> list[DiscoveredFile]:
    """Async wrapper over :func:`discover_files` (runs off the loop)."""
    return await asyncio.to_thread(discover_files, target, root)


__all__ = [
    "DiscoveredFile",
    "EXT_TO_LANGUAGE",
    "MAX_FILE_BYTES",
    "SKIP_DIRS",
    "adiscover_files",
    "discover_files",
    "normalise_root",
    "to_rel_posix",
]
