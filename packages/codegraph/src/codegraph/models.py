"""Plain dataclasses for the code graph.

Single source of truth for the row shapes. Persistence lives in
:mod:`codegraph.graph_store` (Ladybug); these types never touch the
database layer.

Graph contract (v2, raw parser):

- ``Node`` kinds: file | class | function | method | import.
- ``Edge`` kinds: contains (file -> def, class -> method,
  function -> nested def) | imports (file -> import, carrying the raw
  ``target_module`` string) | calls (function|method ->
  function|method|class, bare-name call sites only).
"""

from __future__ import annotations

import enum
import uuid
from dataclasses import dataclass, field


def new_id() -> str:
    """Return a random hex id for a graph row."""
    return uuid.uuid4().hex


class NodeKind(str, enum.Enum):
    """Structural node types extracted by the raw parsers."""

    FILE = "file"
    CLASS = "class"
    FUNCTION = "function"
    METHOD = "method"
    IMPORT = "import"


class EdgeKind(str, enum.Enum):
    """Structural edge types between nodes."""

    CONTAINS = "contains"
    IMPORTS = "imports"
    CALLS = "calls"


@dataclass(slots=True)
class Node:
    """One structural element of a scanned codebase."""

    id: str = field(default_factory=new_id)
    root: str = ""
    file_path: str = ""
    kind: NodeKind = NodeKind.FILE
    name: str = ""
    language: str = ""
    start_line: int = 1
    end_line: int = 1
    parent_id: str | None = None
    is_placeholder: bool = False


@dataclass(slots=True)
class Edge:
    """One structural relation between two nodes.

    ``src_id`` always points at a stored node. ``dst_id`` usually does
    too — except assumed cross-file callee refs (``base:name``), which
    resolve to a placeholder stub node (``is_placeholder``): the stub's
    presence *is* the broken-import signal.
    """

    id: str = field(default_factory=new_id)
    root: str = ""
    src_id: str = ""
    dst_id: str = ""
    kind: EdgeKind = EdgeKind.CONTAINS
    target_module: str | None = None
    site_line: int | None = None


__all__ = ["Edge", "EdgeKind", "Node", "NodeKind", "new_id"]
