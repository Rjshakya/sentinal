"""Database path resolution for the CLI.

The graph lives in an embedded Ladybug database — there is no server,
so ``--db`` accepts only a filesystem path (on-disk ``.lbdb``) or
``:memory:`` (ephemeral):

- ``./codegraph.lbdb`` → on-disk database at that path.
- ``:memory:`` → temporary database, lost when the process exits.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class ResolvedDb:
    """A Ladybug database path plus a human label."""

    path: str
    label: str
    is_memory: bool


def resolve_db(raw: str) -> ResolvedDb:
    """Normalise a ``--db`` value into a Ladybug database path.

    Raises:
        ValueError: when the value is empty or uses a URL scheme
            (Ladybug is embedded — pass a file path or ``:memory:``).
    """
    value: str = raw.strip()
    if not value:
        raise ValueError("--db must not be empty")

    if value == ":memory:":
        return ResolvedDb(path=":memory:", label=":memory:", is_memory=True)

    if "://" in value:
        raise ValueError(
            f"unsupported --db scheme: {value!r} "
            "(expected a file path or :memory: — Ladybug is embedded)"
        )

    path: Path = Path(value).expanduser().resolve()
    return ResolvedDb(path=path.as_posix(), label=path.as_posix(), is_memory=False)


__all__ = ["ResolvedDb", "resolve_db"]
