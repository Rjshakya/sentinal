"""Unit tests: --db resolution (Ladybug path or :memory:)."""

from pathlib import Path

import pytest

from codegraph.cli import build_parser
from codegraph.config import DEFAULT_DB, resolve_db


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


def test_default_db_is_home_known_location() -> None:
    assert DEFAULT_DB == "~/.codegraph/graph.lbdb"
    db = resolve_db(DEFAULT_DB)
    assert not db.is_memory
    assert db.path.endswith(".codegraph/graph.lbdb")
    assert Path(db.path).is_absolute()


def test_parser_db_default_is_shared() -> None:
    parser = build_parser()
    assert parser.parse_args(["index", "some/path"]).db == DEFAULT_DB
    assert parser.parse_args(["stats"]).db == DEFAULT_DB
    assert parser.parse_args(["query", "overview"]).db == DEFAULT_DB
