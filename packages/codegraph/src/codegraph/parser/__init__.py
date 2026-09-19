"""Parser dispatch and graph builder.

:func:`parse_file` picks the language parser by extension (via
``walk.EXT_TO_LANGUAGE``). :func:`build_file_rows` converts one
:class:`ParsedFile` IR into ``Node`` rows plus ``contains`` /
``imports`` edges; :func:`resolve_call_edges` then resolves every
file's :class:`ParsedCall` rows against the global
``(rel_path, name)`` definition map and emits cross-file ``calls``
edges. Callers needing the old single-file behaviour use
:func:`build_file_rows` and ignore the second pass.
"""

from __future__ import annotations

import posixpath
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from codegraph.models import Edge, EdgeKind, Node, NodeKind, new_id
from codegraph.parser.base import ParsedCall, ParsedFile
from codegraph.parser.python import parse_python_source
from codegraph.parser.typescript import (
    parse_javascript_source,
    parse_typescript_source,
)


def parse_source_text(language: str, source_text: str) -> ParsedFile:
    """Dispatch source text to the language parser.

    Raises:
        ValueError: for languages outside the v1 set.
    """
    if language == "python":
        return parse_python_source(source_text)
    if language == "typescript":
        return parse_typescript_source(source_text)
    if language == "javascript":
        return parse_javascript_source(source_text)
    raise ValueError(f"unsupported language: {language!r}")


def parse_file(path: Path, language: str) -> ParsedFile:
    """Read ``path`` and parse it (sync; callers wrap in ``to_thread``)."""
    return parse_source_text(language, path.read_text(encoding="utf-8", errors="ignore"))


@dataclass(slots=True)
class FileRows:
    """Per-file build output: storage rows plus resolution maps.

    ``definitions`` maps def name → node id (first registration wins,
    mirroring the duplicate-name rule); ``imports`` maps imported name
    → module specifier; ``calls`` are the unresolved call intents for
    the global :func:`resolve_call_edges` pass.
    """

    rel_path: str
    language: str
    nodes: list[Node] = field(default_factory=list)
    edges: list[Edge] = field(default_factory=list)
    definitions: dict[str, str] = field(default_factory=dict)
    imports: dict[str, str] = field(default_factory=dict)
    calls: list[ParsedCall] = field(default_factory=list)


def build_file_rows(
    root: str,
    rel_path: str,
    language: str,
    parsed: ParsedFile,
) -> FileRows:
    """Convert one :class:`ParsedFile` into nodes + ``contains`` / ``imports`` edges.

    Links (all derived from the tree-sitter structure hierarchy):

    - ``contains``: file → each top-level def; class → each method;
      function → each nested def.
    - ``imports``: file → each imported name (carries ``target_module``).

    ``calls`` edges are NOT emitted here — call sites resolve across
    files in :func:`resolve_call_edges`. The file node always exists,
    even for empty files. Definitions are visited in preorder, so a
    parent's node id is always registered before its children resolve
    it. Duplicate names in one file resolve to the first registration.
    """
    file_id: str = new_id()
    file_node = Node(
        id=file_id,
        root=root,
        file_path=rel_path,
        kind=NodeKind.FILE,
        name=Path(rel_path).name,
        language=language,
        start_line=1,
        end_line=parsed.total_lines,
        parent_id=None,
    )
    rows = FileRows(rel_path=rel_path, language=language)
    rows.nodes.append(file_node)

    def_ids: dict[str, str] = {}
    for definition in parsed.definitions:
        node_id: str = new_id()
        parent_id: str = file_id
        if definition.parent is not None and definition.parent in def_ids:
            parent_id = def_ids[definition.parent]
        kind = NodeKind.CLASS if definition.kind == "class" else NodeKind.FUNCTION
        rows.nodes.append(
            Node(
                id=node_id,
                root=root,
                file_path=rel_path,
                kind=kind,
                name=definition.name,
                language=language,
                start_line=definition.start_line,
                end_line=definition.end_line,
                parent_id=parent_id,
            )
        )
        rows.edges.append(
            Edge(
                id=new_id(),
                root=root,
                src_id=parent_id,
                dst_id=node_id,
                kind=EdgeKind.CONTAINS,
                target_module=None,
            )
        )
        def_ids.setdefault(definition.name, node_id)
        rows.definitions.setdefault(definition.name, node_id)

    for imported in parsed.imports:
        node_id = new_id()
        rows.nodes.append(
            Node(
                id=node_id,
                root=root,
                file_path=rel_path,
                kind=NodeKind.IMPORT,
                name=imported.name,
                language=language,
                start_line=imported.start_line,
                end_line=imported.end_line,
                parent_id=file_id,
            )
        )
        rows.edges.append(
            Edge(
                id=new_id(),
                root=root,
                src_id=file_id,
                dst_id=node_id,
                kind=EdgeKind.IMPORTS,
                target_module=imported.module,
            )
        )
        rows.imports.setdefault(imported.name, imported.module)

    rows.calls.extend(parsed.calls)
    return rows


_TS_EXTENSIONS: tuple[str, ...] = (".ts", ".tsx", ".js", ".jsx")
"""Candidate extensions when resolving a relative TS/JS module."""


def _resolve_python_module(
    module: str, importer_rel: str, indexed: set[str]
) -> str | None:
    """Resolve a Python module specifier to an indexed ``rel_path``.

    Absolute dotted modules match by trailing path components
    (``app.workflows.review_v2.steps.get_repo`` → an indexed
    ``steps/get_repo.py`` — the module is rooted above the indexed
    root, so every trailing-component suffix is tried longest-first),
    with an ``__init__.py`` package fallback per suffix. Relative
    modules (leading dots) resolve against the importer's directory.
    Ambiguous matches resolve deterministically to the
    lexicographically smallest path.
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


def _resolve_ts_module(
    module: str, importer_rel: str, indexed: set[str]
) -> str | None:
    """Resolve a relative TS/JS module specifier to an indexed ``rel_path``.

    Only relative specifiers (``./x``, ``../lib/y``) resolve — bare
    package specifiers (``react``, ``@scope/x``) never do. Tries the
    literal path plus known extensions and ``/index`` fallbacks.
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


def _resolve_module(
    module: str, importer_rel: str, language: str, indexed: set[str]
) -> str | None:
    """Resolve a module specifier to an indexed ``rel_path`` (or ``None``)."""
    if language in ("typescript", "javascript"):
        return _resolve_ts_module(module, importer_rel, indexed)
    return _resolve_python_module(module, importer_rel, indexed)


def resolve_call_edges(files: list[FileRows], root: str) -> list[Edge]:
    """Resolve every file's call intents into ``calls`` edges.

    A callee resolves to a same-file definition first, then to a
    definition in the file its import specifier resolves to (function
    *or* class nodes — class instantiation is a call). Anything else
    (builtins, stdlib, third-party, unresolvable names) yields no
    edge, never a dangling one. Duplicate call sites collapse to one
    edge per caller → callee pair; recursion (caller == callee) is
    kept as a truthful self-edge.
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
    "FileRows",
    "build_file_rows",
    "parse_file",
    "parse_source_text",
    "resolve_call_edges",
]
