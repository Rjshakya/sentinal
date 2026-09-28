"""Cross-file linking: import map + call-edge join (pure).

Two-pass join for the Python pipeline:

1. Collect (per file, no global state): defs, imports with alias
   originals, buffered bare-name call sites — see
   :mod:`codegraph.parser.lang_python` and :mod:`codegraph.parser.rows`.
2. Link (here, global state): one :class:`ImportEntry` per bound name
   (module specifier -> resolved ``rel_path``), then every call site
   joins ``(file, name)`` against the definition registry. Anything
   unresolvable yields no edge — never a dangling one.
"""

from __future__ import annotations

import posixpath
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from codegraph.models import Edge, EdgeKind, new_id
from codegraph.parser.rows import FileRows


@dataclass(frozen=True, slots=True)
class ImportEntry:
    """One bound name's import map row: specifier + resolved target file."""

    module: str  # raw module specifier, e.g. "pkg.utils" | ".sibling"
    bound: str  # name bound in the importing file, e.g. "h"
    original: str  # name in the defining module, e.g. "helper"
    resolved_rel: str | None  # indexed rel_path of the target, if any


def build_import_index(file_set: Iterable[str]) -> dict[str, str]:
    """Build the frozen ``absolute dotted module -> rel_path`` index.

    Pure path math over POSIX rel paths — no parsing, no I/O. Covers
    ``pkg/utils.py`` → ``pkg.utils`` plus the ``pkg/__init__.py`` →
    ``pkg`` package fallback. First registration wins.

    Retained for the (currently unwired) TS/Go emitters and their unit
    tests; the Python link phase below resolves modules with
    root-prefix-tolerant suffix matching instead.
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
    """Resolve a Python module specifier to an indexed ``rel_path``.

    Relative specifiers resolve against the importer's directory
    (root-prefix agnostic by construction). Absolute specifiers match
    the longest specifier suffix against indexed stems, tolerating a
    root-relative prefix on the indexed side (``src.app.x`` satisfies
    ``import app.x``) — the ``src/app`` vs ``app`` skew.
    """
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
    parts: list[str] = [p for p in module.split(".") if p]
    if not parts:
        return None
    stems: dict[str, str] = {}
    for path in indexed:
        if not path.endswith(".py"):
            continue
        stems.setdefault(path[: -len(".py")].replace("/", "."), path)
    for start in range(len(parts)):
        suffix: str = ".".join(parts[start:])
        init_suffix: str = suffix + ".__init__"
        matches: list[str] = sorted(
            path
            for stem, path in stems.items()
            if stem == suffix
            or stem.endswith("." + suffix)
            or stem == init_suffix
            or stem.endswith("." + init_suffix)
        )
        if matches:
            matches.sort(key=lambda p: (len(p), p))
            return matches[0]
    return None


def build_file_import_map(
    rows: FileRows, indexed: set[str]
) -> dict[str, ImportEntry]:
    """Build one file's bound-name -> :class:`ImportEntry` map.

    First registration wins per bound name. Star imports (``*``) and
    Go dot imports (``.``) are recorded but never resolve a bare call
    site directly — export tracking is out of scope (Go dot-imported
    files are searched separately, see :func:`build_dot_import_targets`).
    """
    file_map: dict[str, ImportEntry] = {}
    for parsed_import in rows.import_details:
        if parsed_import.name in file_map:
            continue
        if parsed_import.name in ("*", "."):
            file_map.setdefault(
                parsed_import.name,
                ImportEntry(
                    module=parsed_import.module,
                    bound=parsed_import.name,
                    original=parsed_import.effective_original,
                    resolved_rel=None,
                ),
            )
            continue
        resolved: str | None = _resolve_module(
            parsed_import.module, rows.rel_path, rows.language, indexed
        )
        file_map.setdefault(
            parsed_import.name,
            ImportEntry(
                module=parsed_import.module,
                bound=parsed_import.name,
                original=parsed_import.effective_original,
                resolved_rel=resolved,
            ),
        )
    return file_map


def build_dot_import_targets(rows: FileRows, indexed: set[str]) -> list[str]:
    """Return resolved files this Go file dot-imports, sorted.

    A dot import (``import . "pkg/utils"``) brings the package's
    exported names into unqualified scope, so bare call sites fall
    back to these files' definitions when no import-map entry matches.
    Non-Go files and files without dot imports yield ``[]``.
    """
    if rows.language != "go":
        return []
    targets: set[str] = set()
    for parsed_import in rows.import_details:
        if parsed_import.name != ".":
            continue
        resolved: str | None = _resolve_go_module(
            parsed_import.module, rows.rel_path, indexed
        )
        if resolved is not None:
            targets.add(resolved)
    return sorted(targets)


def _resolve_ts_module(module: str, importer_rel: str, indexed: set[str]) -> str | None:
    """Resolve a relative TS/JS module specifier to an indexed ``rel_path``.

    Bare specifiers (npm packages) never resolve — they have no file.
    """
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
    """Resolve a Go import path to an indexed ``rel_path``.

    Relative paths resolve against the importer's directory; otherwise
    the import tail (package base name) matches the indexed ``.go``
    stem, shortest path first for determinism.
    """
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
    """Resolve every file's buffered call sites into ``calls`` edges.

    Resolution order per site: same-file definition first, then the
    callee's import-map entry joined against the resolved file's
    definitions on a single candidate name — the *original*
    (defining-module) name when the import carries one
    (``from utils import helper as h`` → ``helper``), else the bound
    name (plain and default imports). Go files additionally fall back
    to their dot-imported files' definitions. The join key is the
    ``(rel_path, name)`` registry pair — dotted module strings never
    take part, so a root-relative prefix on indexed paths (``src/app``
    vs ``import app``) cannot break the join.

    A callee may be a function, method, class, interface, *or* type
    node — class instantiation and ``new C()`` are calls. Anything
    else (natives, stdlib / third-party / unindexed modules,
    star-import calls, names missing from the target file) yields no
    edge, never a dangling one. One edge per caller → callee pair,
    stamped with the call-site line.
    """
    indexed: set[str] = {rows.rel_path for rows in files}
    def_ids: dict[tuple[str, str], str] = {}
    for rows in files:
        for name, node_id in rows.definitions.items():
            def_ids.setdefault((rows.rel_path, name), node_id)
    file_maps: dict[str, dict[str, ImportEntry]] = {
        rows.rel_path: build_file_import_map(rows, indexed) for rows in files
    }
    dot_targets: dict[str, list[str]] = {
        rows.rel_path: build_dot_import_targets(rows, indexed) for rows in files
    }
    seen: set[tuple[str, str]] = set()
    edges: list[Edge] = []
    for rows in files:
        file_map: dict[str, ImportEntry] = file_maps[rows.rel_path]
        dots: list[str] = dot_targets[rows.rel_path]
        for call in rows.calls:
            src_id: str | None = def_ids.get((rows.rel_path, call.caller))
            if src_id is None:
                continue
            dst_id: str | None = def_ids.get((rows.rel_path, call.callee))
            if dst_id is None:
                entry: ImportEntry | None = file_map.get(call.callee)
                if entry is not None and entry.resolved_rel is not None:
                    candidate: str = (
                        entry.original if entry.original else entry.bound
                    )
                    dst_id = def_ids.get((entry.resolved_rel, candidate))
                if dst_id is None:
                    for target in dots:
                        dst_id = def_ids.get((target, call.callee))
                        if dst_id is not None:
                            break
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
                    site_line=call.site_line,
                )
            )
    return edges


__all__ = [
    "ImportEntry",
    "build_dot_import_targets",
    "build_file_import_map",
    "build_import_index",
    "resolve_call_edges",
]
