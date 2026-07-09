"""Embedding model + legacy helper used by the in-sandbox scripts.

The new ingestion flow (``ingestion.py``) uses the lancedb registry
``model`` declared below — LanceDB computes and stores the ``vector``
column on ``table.add(...)`` itself, so ingestion no longer pre-embeds
chunks.

``create_embeddings`` is kept as a thin async shim for ``search.py``,
which still embeds the query by hand before calling ``table.query()``.
That call is on the to-do list; the shim keeps the search path working
unchanged in the meantime.
"""

from __future__ import annotations

import logging

from lancedb.embeddings import get_registry
from openai import AsyncClient

log = logging.getLogger(__name__)

# Used by ingestion.py for auto-embedding on table.add(...).
model = get_registry().get("openai").create(name="text-embedding-3-large")

_client = AsyncClient()


async def create_embeddings(input: list[str]):
    return await _client.embeddings.create(input=input, model="text-embedding-3-large")
