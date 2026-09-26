"""Plain dataclasses for the code graph.

Single source of truth for the row shapes. Persistence lives in
:mod:`codegraph.graph_store` (Ladybug); these types never touch the
database layer.

Graph contract (two-pass build: Python, TypeScript/JavaScript, Go):

- ``Node`` kinds: file | class | function | method | interface |
  type | import. Interfaces own their method signatures; type aliases
  are leaves.
- ``Edge`` kinds: contains (file -> def, class/interface -> method,
  function -> nested def) | imports (file -> import, carrying the raw
  ``target_module`` string) | calls (function|method ->
  function|method|class, bare-name call sites only, real node ids).
- Unresolvable call sites are dropped at build time: every stored
  ``calls`` edge has both endpoints, and no placeholder rows are
  written (``is_placeholder`` stays on the schema for old databases).
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
    INTERFACE = "interface"
    TYPE = "type"
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

    Both ``src_id`` and ``dst_id`` always point at stored nodes; the
    link phase drops call sites that resolve to nothing instead of
    emitting dangling refs.
    """

    id: str = field(default_factory=new_id)
    root: str = ""
    src_id: str = ""
    dst_id: str = ""
    kind: EdgeKind = EdgeKind.CONTAINS
    target_module: str | None = None
    site_line: int | None = None


__all__ = ["Edge", "EdgeKind", "Node", "NodeKind", "new_id"]
