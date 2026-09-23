"""Unit tests: --db resolution (Ladybug path or :memory:)."""

from pathlib import Path

import pytest

from codegraph.config import resolve_db


def test_bare_path_is_on_disk(tmp_path: Path) -> None:
    db = resolve_db(str(tmp_path / "g.lbdb"))
    assert not db.is_memory
    assert db.path.endswith("g.lbdb")
    assert db.label == db.path


def test_memory_db() -> None:
    db = resolve_db(":memory:")
    assert db.is_memory
    assert db.path == ":memory:"


def test_url_scheme_rejected() -> None:
    with pytest.raises(ValueError):
        resolve_db("postgresql://u:p@localhost:5432/aicode")


def test_unsupported_scheme() -> None:
    with pytest.raises(ValueError):
        resolve_db("mysql://localhost/db")


def test_empty_db() -> None:
    with pytest.raises(ValueError):
        resolve_db("   ")
