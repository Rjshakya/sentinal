"""Database URL resolution for the CLI.

The ``--db`` flag accepts either a filesystem path (SQLite) or a full
SQLAlchemy URL (SQLite or Postgres):

- ``./codegraph.db`` → ``sqlite+aiosqlite:///...``
- ``sqlite:///codegraph.db`` / ``sqlite+aiosqlite:///…`` → normalised
  to the async driver.
- ``postgresql+asyncpg://…`` → used as-is.
- anything with ``://`` that is not sqlite/postgres → ``ValueError``.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


SQLITE_PREFIXES: tuple[str, ...] = ("sqlite:///", "sqlite+aiosqlite:///")
POSTGRES_PREFIXES: tuple[str, ...] = (
    "postgresql://",
    "postgresql+asyncpg://",
    "postgres://",
    "postgres+asyncpg://",
)


@dataclass(frozen=True, slots=True)
class ResolvedDb:
    """A normalised async SQLAlchemy URL plus a human label."""

    url: str
    label: str
    is_sqlite: bool


def resolve_db(raw: str) -> ResolvedDb:
    """Normalise a ``--db`` value into an async SQLAlchemy URL.

    Raises:
        ValueError: when the value is empty or uses an unsupported scheme.
    """
    value: str = raw.strip()
    if not value:
        raise ValueError("--db must not be empty")

    if "://" not in value:
        path: Path = Path(value).expanduser().resolve()
        return ResolvedDb(
            url=f"sqlite+aiosqlite:///{path.as_posix()}",
            label=path.as_posix(),
            is_sqlite=True,
        )

    if value.startswith(SQLITE_PREFIXES):
        # Normalise the sync driver prefix to the async one.
        normalised: str = value.replace("sqlite:///", "sqlite+aiosqlite:///", 1)
        return ResolvedDb(url=normalised, label=value, is_sqlite=True)

    if value.startswith(POSTGRES_PREFIXES):
        normalised_pg: str = value
        if "+asyncpg" not in normalised_pg:
            normalised_pg = normalised_pg.replace("://", "+asyncpg://", 1)
        return ResolvedDb(url=normalised_pg, label=value, is_sqlite=False)

    raise ValueError(
        f"unsupported --db scheme: {value!r} "
        "(expected a file path, sqlite://…, or postgresql://…)"
    )


__all__ = ["ResolvedDb", "resolve_db"]
