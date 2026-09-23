"""Cross-file linking: module index + call-edge join (pure)."""

from __future__ import annotations

import posixpath
from collections.abc import Iterable
from pathlib import Path, PurePosixPath

from codegraph.models import Edge, EdgeKind, new_id
from codegraph.parser.rows import FileRows


def build_import_index(file_set: Iterable[str]) -> dict[str, str]:
    """Build the frozen ``absolute dotted module -> rel_path`` index.

    Pure path math over POSIX rel paths — no parsing, no I/O. Covers
    ``pkg/utils.py`` → ``pkg.utils`` plus the ``pkg/__init__.py`` →
    ``pkg`` package fallback. First registration wins.
    """
    index: dict[str, str] = {}
    for rel in sorted(file_set):
        # rel->rel overlay: TS/Go emitters probe relative candidates
        # directly via ``import_index.get`` on the same mapping.
        index.setdefault(rel, rel)
        if not rel.endswith(".py"):
            continue
        stem: str = rel[: -len(".py")]
        dotted: str = stem.replace("/", ".")
        index.setdefault(dotted, rel)
        if stem.endswith("/__init__"):
            index.setdefault(dotted[: -len(".__init__")], rel)
        elif stem == "__init__":
            index.setdefault("", rel)
    return index


_TS_EXTENSIONS: tuple[str, ...] = (".ts", ".tsx", ".js", ".jsx")
"""Candidate extensions when resolving a relative TS/JS module."""


def _resolve_python_module(
    module: str, importer_rel: str, indexed: set[str]
) -> str | None:
    """Resolve a Python module specifier to an indexed ``rel_path``."""
    if module.startswith("."):
        level: int = len(module) - len(module.lstrip("."))
        rest: str = module.lstrip(".")
        base = PurePosixPath(importer_rel).parent
        for _ in range(level - 1):
            base = base.parent
        target: str = (
            (base / PurePosixPath(*rest.split("."))).as_posix() if rest else base.as_posix()
        )
        for trial in (target + ".py", target + "/__init__.py"):
            if trial in indexed:
                return trial
        return None
    parts: list[str] = module.split(".")
    for start in range(len(parts)):
        suffix: str = "/".join(parts[start:])
        matches: list[str] = sorted(
            path
            for path in indexed
            if path == suffix + ".py" or path == suffix + "/__init__.py"
        )
        if matches:
            return matches[0]
    return None


def _resolve_ts_module(module: str, importer_rel: str, indexed: set[str]) -> str | None:
    """Resolve a relative TS/JS module specifier to an indexed ``rel_path``."""
    if not module.startswith("."):
        return None
    base: str = posixpath.normpath(
        posixpath.join(posixpath.dirname(importer_rel), module)
    )
    candidates: list[str] = [base]
    candidates.extend(base + ext for ext in _TS_EXTENSIONS)
    candidates.extend(base + "/index" + ext for ext in _TS_EXTENSIONS)
    for trial in candidates:
        if trial in indexed:
            return trial
    return None


def _resolve_go_module(module: str, importer_rel: str, indexed: set[str]) -> str | None:
    """Resolve a Go import path to an indexed ``rel_path``."""
    if module.startswith("."):
        base: str = posixpath.normpath(
            posixpath.join(posixpath.dirname(importer_rel), module)
        )
        for trial in (base, base + ".go"):
            if trial in indexed:
                return trial
        return None
    tail: str = module.rsplit("/", 1)[-1]
    if not tail:
        return None
    candidates: list[str] = sorted(
        path for path in indexed if Path(path).stem == tail and path.endswith(".go")
    )
    if not candidates:
        return None
    candidates.sort(key=lambda p: (len(p), p))
    return candidates[0]


def _resolve_module(
    module: str, importer_rel: str, language: str, indexed: set[str]
) -> str | None:
    """Resolve a module specifier to an indexed ``rel_path`` (or ``None``)."""
    if language in ("typescript", "javascript"):
        return _resolve_ts_module(module, importer_rel, indexed)
    if language == "go":
        return _resolve_go_module(module, importer_rel, indexed)
    return _resolve_python_module(module, importer_rel, indexed)


def resolve_call_edges(files: list[FileRows], root: str) -> list[Edge]:
    """Resolve every file's call intents into ``calls`` edges.

    A callee resolves to a same-file definition first, then to a
    definition in the file its import specifier resolves to (function,
    method, *or* class nodes — class instantiation is a call). Anything
    else yields no edge, never a dangling one. One edge per caller →
    callee pair.
    """
    indexed: set[str] = {rows.rel_path for rows in files}
    def_ids: dict[tuple[str, str], str] = {}
    for rows in files:
        for name, node_id in rows.definitions.items():
            def_ids[(rows.rel_path, name)] = node_id
    seen: set[tuple[str, str]] = set()
    edges: list[Edge] = []
    for rows in files:
        for call in rows.calls:
            src_id: str | None = def_ids.get((rows.rel_path, call.caller))
            if src_id is None:
                continue
            dst_id: str | None = def_ids.get((rows.rel_path, call.callee))
            if dst_id is None:
                module: str | None = rows.imports.get(call.callee)
                if module is None:
                    continue
                target: str | None = _resolve_module(
                    module, rows.rel_path, rows.language, indexed
                )
                if target is None:
                    continue
                dst_id = def_ids.get((target, call.callee))
                if dst_id is None:
                    continue
            if (src_id, dst_id) in seen:
                continue
            seen.add((src_id, dst_id))
            edges.append(
                Edge(
                    id=new_id(),
                    root=root,
                    src_id=src_id,
                    dst_id=dst_id,
                    kind=EdgeKind.CALLS,
                    target_module=None,
                )
            )
    return edges


__all__ = [
    "build_import_index",
    "resolve_call_edges",
]
