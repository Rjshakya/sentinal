"""Pure helpers for the search service.

No I/O, no session, no settings reads — every function here is
testable with ``assert f(x) == y``. Mirrors the convention from
:mod:`app.services.indexing.helpers`.
"""

from __future__ import annotations

from app.services.indexing.helpers import build_table_uri

__all__ = [
    "build_table_uri",
    "parse_node_types",
]


def parse_node_types(raw: object) -> list[str]:
    """Parse the in-storage ``node_types`` value into a list of strings.

    The in-sandbox ingestion step stores ``node_types`` as a
    comma-separated string (``", ".join(map(str, chunk.node_types))``
    in :mod:`app.services.indexing.scripts.ingestion`). LanceDB may
    surface that field as ``str`` or, depending on the dataset's
    schema, as a ``list[str]``; this helper accepts either and returns
    a ``list[str]`` of trimmed non-empty items.

    The function is intentionally permissive: it never raises and
    returns ``[]`` for ``None``, ``""``, or non-iterable scalars.
    """
    if raw is None:
        return []
    if isinstance(raw, list):
        return [str(item).strip() for item in raw if str(item).strip()]
    if isinstance(raw, str):
        return [part.strip() for part in raw.split(",") if part.strip()]
    text = str(raw).strip()
    if not text:
        return []
    return [part.strip() for part in text.split(",") if part.strip()]
