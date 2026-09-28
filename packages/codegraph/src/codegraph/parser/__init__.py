"""Parser barrel: re-exports only, no logic.

Per-file rows live in :mod:`codegraph.parser.rows`, cross-file
linking (import map + call join) in :mod:`codegraph.parser.links`,
the Python collect phase in :mod:`codegraph.parser.lang_python`;
``lang_go`` / ``lang_typescript`` are kept, currently unwired.
"""

from codegraph.parser.links import (
    ImportEntry,
    build_dot_import_targets,
    build_file_import_map,
    build_import_index,
    resolve_call_edges,
)
from codegraph.parser.rows import FileRows, build_file_rows, build_python_file_rows

__all__ = [
    "FileRows",
    "ImportEntry",
    "build_dot_import_targets",
    "build_file_import_map",
    "build_file_rows",
    "build_import_index",
    "build_python_file_rows",
    "resolve_call_edges",
]
