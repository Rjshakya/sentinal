"""Step: host-side deletion of stale chunks from the repo's LanceDB dataset.

The one LanceDB mutation that runs on the API host rather than in the
sandbox — it needs no repo content and no embeddings, so spinning up a
sandbox for it would waste minutes on every push. (Reads already run
host-side in :mod:`app.services.search.service`; the host writes
nothing here beyond the delete.)

Flow:

1. Gate on :attr:`Settings.indexing_configured` — final
   :class:`IndexingConfigError`.
2. ``lancedb.connect_async(uri, storage_options=...)`` — transient
   S3 / transport failures wrap in :class:`DeleteChunksTransientError`
   so DBOS retries the whole step (the delete is idempotent).
3. ``table_names()`` — a repo marked indexed with no ``context``
   table is a data inconsistency, surfaced as a final
   :class:`DeleteChunksError` (not retried).
4. ``table.delete(predicate)`` per :data:`DELETE_BATCH_SIZE`-chunked
   predicate; sums the row counts into the return value.

The FTS index is managed by LanceDB and stays in sync with deletes on
this version (>= 0.36); the append run's ``create_fts_index(replace=True)``
rebuilds it as an extra safety net.
"""

from __future__ import annotations

import logging

import lancedb
from dbos import DBOS

from app.core.config import settings
from app.services.indexing.errors import (
    IndexingConfigError,
    _should_retry_index,
)
from app.services.indexing.incremental.errors import (
    DeleteChunksError,
    DeleteChunksTransientError,
)
from app.services.indexing.incremental.helpers import build_delete_query

log = logging.getLogger(__name__)

INDEX_TABLE_NAME: str = "context"


def _storage_options() -> dict[str, str]:
    """S3-compatible storage options forwarded to LanceDB (mirrors search)."""
    return {
        "endpoint": settings.aws_endpoint_url,
        "region": settings.aws_region,
        "access_key_id": settings.aws_access_key_id,
        "secret_access_key": settings.aws_secret_access_key,
    }


@DBOS.step(
    retries_allowed=True,
    max_attempts=3,
    should_retry=_should_retry_index,
)
async def deleteStaleChunksStep(*, table_uri: str, files: list[str]) -> int:
    """Drop every chunk whose ``file_name`` is in ``files``.

    Returns the number of LanceDB rows deleted (0 when ``files`` is
    empty or nothing matched). Pure deletes never touch a sandbox.

    Raises:
        IndexingConfigError: the indexing stack is not configured. Final.
        DeleteChunksTransientError: LanceDB / S3 transport failure.
            Transient — DBOS retries.
        DeleteChunksError: the ``context`` table is missing from a
            repo the mirror marked indexed. Final.
    """
    if not files:
        return 0

    if not settings.indexing_configured:
        raise IndexingConfigError()

    try:
        db = await lancedb.connect_async(table_uri, storage_options=_storage_options())
    except Exception as exc:
        log.warning(
            "delete_stale_chunks: connect failed table_uri=%s cause=%s: %s",
            table_uri,
            type(exc).__name__,
            exc,
        )
        raise DeleteChunksTransientError(
            cause=f"lancedb connect failed: {type(exc).__name__}: {exc}"
        ) from exc

    try:
        table = await db.open_table(INDEX_TABLE_NAME)

        deleted = len(files)
        query = build_delete_query(files)

        await table.delete(query)

    except DeleteChunksError:
        raise
    except Exception as exc:
        log.warning(
            "delete_stale_chunks: delete failed table_uri=%s files=%d cause=%s: %s",
            table_uri,
            len(files),
            type(exc).__name__,
            exc,
        )
        raise DeleteChunksTransientError(
            cause=f"lancedb delete failed: {type(exc).__name__}: {exc}"
        ) from exc

    log.info(
        "delete_stale_chunks: ok table_uri=%s files=%d deleted=%d",
        table_uri,
        len(files),
        deleted,
    )
    return deleted


__all__ = ["deleteStaleChunksStep"]
