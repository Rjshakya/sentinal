"""SQLModel tables for the code graph.

Single source of truth for the schema (per repo convention: SQLModel
defines the shape; the CLI creates it via ``create_all``). The same
models drive both backends — SQLite (default) and Postgres (``--db``
flag) — so there is no per-backend duplication.

Graph contract (v1, structure only):

- ``Node`` kinds: file | class | function | import.
- ``Edge`` kinds: contains (file -> class/function, class -> method)
  | imports (file -> import, carrying the raw ``target_module`` string).
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
    """Structural node types extracted by the parsers."""

    FILE = "file"
    CLASS = "class"
    FUNCTION = "function"
    IMPORT = "import"


class EdgeKind(str, enum.Enum):
    """Structural edge types between nodes."""

    CONTAINS = "contains"
    IMPORTS = "imports"


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
    """One structural relation between two nodes."""

    __tablename__ = "codegraph_edge"  # type: ignore[assignment]

    id: str = Field(default_factory=new_id, primary_key=True)
    root: str = Field(nullable=False, index=True)
    src_id: str = Field(nullable=False, foreign_key="codegraph_node.id", index=True)
    dst_id: str = Field(nullable=False, foreign_key="codegraph_node.id", index=True)
    kind: EdgeKind = Field(sa_column=Column(String(16), nullable=False, index=True))
    target_module: str | None = Field(
        default=None, sa_column=Column(Text, nullable=True)
    )

    created_at: datetime = Field(
        default_factory=utcnow,
        sa_column=Column(
            TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")
        ),
    )


__all__ = ["Edge", "EdgeKind", "Node", "NodeKind", "new_id", "utcnow"]
