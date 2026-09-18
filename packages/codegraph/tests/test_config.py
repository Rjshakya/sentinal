"""Unit tests: --db resolution (SQLite default, Postgres flag)."""

from pathlib import Path

import pytest

from codegraph.config import resolve_db


def test_bare_path_is_sqlite(tmp_path: Path) -> None:
    db = resolve_db(str(tmp_path / "g.db"))
    assert db.is_sqlite
    assert db.url.startswith("sqlite+aiosqlite:///")


def test_postgres_flag() -> None:
    db = resolve_db("postgresql://u:p@localhost:5432/aicode")
    assert not db.is_sqlite
    assert db.url.startswith("postgresql+asyncpg://")


def test_unsupported_scheme() -> None:
    with pytest.raises(ValueError):
        resolve_db("mysql://localhost/db")


def test_empty_db() -> None:
    with pytest.raises(ValueError):
        resolve_db("   ")
