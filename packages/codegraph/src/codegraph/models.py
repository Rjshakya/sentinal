"""SQLModel tables for the code graph.

Single source of truth for the schema (per repo convention: SQLModel
defines the shape; the CLI creates it via ``create_all``). The same
models drive both backends — SQLite (default) and Postgres (``--db``
flag) — so there is no per-backend duplication.

Graph contract (v2, raw parser):

- ``Node`` kinds: file | class | function | method | import.
- ``Edge`` kinds: contains (file -> def, class -> method,
  function -> nested) | imports (file -> import, carrying the raw
  ``target_module`` string) | calls (function|method ->
  function|method|class, bare-name call sites only).
"""

from __future__ import annotations

import enum
import uuid
from datetime import UTC, datetime

from sqlalchemy import Column, String, Text, text
from sqlalchemy.dialects.postgresql import TIMESTAMP
from sqlmodel import Field, SQLModel


def new_id() -> str:
    """Return a random hex id for a graph row."""
    return uuid.uuid4().hex


def utcnow() -> datetime:
    """Return the current UTC time (used as a default factory)."""
    return datetime.now(UTC)


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


class Node(SQLModel, table=True):
    """One structural element of a scanned codebase."""

    __tablename__ = "codegraph_node"  # type: ignore[assignment]

    id: str = Field(default_factory=new_id, primary_key=True)
    root: str = Field(nullable=False, index=True)
    file_path: str = Field(nullable=False, index=True)
    kind: NodeKind = Field(sa_column=Column(String(16), nullable=False, index=True))
    name: str = Field(nullable=False)
    language: str = Field(nullable=False, index=True)
    start_line: int = Field(nullable=False)
    end_line: int = Field(nullable=False)
    parent_id: str | None = Field(default=None, foreign_key="codegraph_node.id")

    created_at: datetime = Field(
        default_factory=utcnow,
        sa_column=Column(
            TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")
        ),
    )


class Edge(SQLModel, table=True):
    """One structural relation between two nodes.

    ``src_id`` always points at a stored node. ``dst_id`` usually does
    too — except assumed cross-file callee refs (``base:name``), which
    dangle by design when the target is missing: the querier's miss on
    the node lookup is the broken-import signal.

    ``site_line`` is the 1-based line of the call site inside the
    caller (``calls`` edges from the Python v2 emitter only); ``None``
    means unknown (other languages, older rows). Renderers sort
    callees by it to show implementation order.
    """

    __tablename__ = "codegraph_edge"  # type: ignore[assignment]

    id: str = Field(default_factory=new_id, primary_key=True)
    root: str = Field(nullable=False, index=True)
    src_id: str = Field(nullable=False, foreign_key="codegraph_node.id", index=True)
    dst_id: str = Field(nullable=False, index=True)
    kind: EdgeKind = Field(sa_column=Column(String(16), nullable=False, index=True))
    target_module: str | None = Field(
        default=None, sa_column=Column(Text, nullable=True)
    )
    site_line: int | None = Field(default=None, nullable=True)

    created_at: datetime = Field(
        default_factory=utcnow,
        sa_column=Column(
            TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")
        ),
    )


__all__ = ["Edge", "EdgeKind", "Node", "NodeKind", "new_id", "utcnow"]
