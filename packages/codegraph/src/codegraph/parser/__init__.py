"""Parser barrel: re-exports only, no logic.

Per-file rows live in :mod:`codegraph.parser.rows`, cross-file
linking in :mod:`codegraph.parser.links`, language extractors in
:mod:`codegraph.parser.lang_python` (v2 single-pass emitter) plus
``lang_go`` / ``lang_typescript`` (kept, currently unwired).
"""

from codegraph.parser.links import build_import_index, resolve_call_edges
from codegraph.parser.rows import FileRows, build_file_rows, build_python_file_rows

__all__ = [
    "FileRows",
    "build_file_rows",
    "build_import_index",
    "build_python_file_rows",
    "resolve_call_edges",
]
