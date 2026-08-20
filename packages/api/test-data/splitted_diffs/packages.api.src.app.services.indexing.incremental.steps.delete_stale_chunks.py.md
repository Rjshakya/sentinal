### packages/api/src/app/services/indexing/incremental/steps/delete_stale_chunks.py

```diff

deleted file mode 100644
index 8acffe9..0000000
--- a/packages/api/src/app/services/indexing/incremental/steps/delete_stale_chunks.py
+++ /dev/null
@@ -1,128 +0,0 @@
    2       -"""Step: host-side deletion of stale chunks from the repo's LanceDB dataset.
    3       -
    4       -The one LanceDB mutation that runs on the API host rather than in the
    5       -sandbox — it needs no repo content and no embeddings, so spinning up a
    6       -sandbox for it would waste minutes on every push. (Reads already run
    7       -host-side in :mod:`app.services.search.service`; the host writes
    8       -nothing here beyond the delete.)
    9       -
   10       -Flow:
   11       -
   12       -1. Gate on :attr:`Settings.indexing_configured` — final
   13       -   :class:`IndexingConfigError`.
   14       -2. ``lancedb.connect_async(uri, storage_options=...)`` — transient
   15       -   S3 / transport failures wrap in :class:`DeleteChunksTransientError`
   16       -   so DBOS retries the whole step (the delete is idempotent).
   17       -3. ``table_names()`` — a repo marked indexed with no ``context``
   18       -   table is a data inconsistency, surfaced as a final
   19       -   :class:`DeleteChunksError` (not retried).
   20       -4. ``table.delete(predicate)`` per :data:`DELETE_BATCH_SIZE`-chunked
   21       -   predicate; sums the row counts into the return value.
   22       -
   23       -The FTS index is managed by LanceDB and stays in sync with deletes on
   24       -this version (>= 0.36); the append run's ``create_fts_index(replace=True)``
   25       -rebuilds it as an extra safety net.
   26       -"""
   27       -
   28       -from __future__ import annotations
   29       -
   30       -import logging
   31       -
   32       -import lancedb
   33       -from dbos import DBOS
   34       -
   35       -from app.core.config import settings
   36       -from app.services.indexing.errors import (
   37       -    IndexingConfigError,
   38       -    _should_retry_index,
   39       -)
   40       -from app.services.indexing.incremental.errors import (
   41       -    DeleteChunksError,
   42       -    DeleteChunksTransientError,
   43       -)
   44       -from app.services.indexing.incremental.helpers import build_delete_query
   45       -
   46       -log = logging.getLogger(__name__)
   47       -
   48       -INDEX_TABLE_NAME: str = "context"
   49       -
   50       -
   51       -def _storage_options() -> dict[str, str]:
   52       -    """S3-compatible storage options forwarded to LanceDB (mirrors search)."""
   53       -    return {
   54       -        "endpoint": settings.aws_endpoint_url,
   55       -        "region": settings.aws_region,
   56       -        "access_key_id": settings.aws_access_key_id,
   57       -        "secret_access_key": settings.aws_secret_access_key,
   58       -    }
   59       -
   60       -
   61       -@DBOS.step(
   62       -    retries_allowed=True,
   63       -    max_attempts=3,
   64       -    should_retry=_should_retry_index,
   65       -)
   66       -async def deleteStaleChunksStep(*, table_uri: str, files: list[str]) -> int:
   67       -    """Drop every chunk whose ``file_name`` is in ``files``.
   68       -
   69       -    Returns the number of LanceDB rows deleted (0 when ``files`` is
   70       -    empty or nothing matched). Pure deletes never touch a sandbox.
   71       -
   72       -    Raises:
   73       -        IndexingConfigError: the indexing stack is not configured. Final.
   74       -        DeleteChunksTransientError: LanceDB / S3 transport failure.
   75       -            Transient — DBOS retries.
   76       -        DeleteChunksError: the ``context`` table is missing from a
   77       -            repo the mirror marked indexed. Final.
   78       -    """
   79       -    if not files:
   80       -        return 0
   81       -
   82       -    if not settings.indexing_configured:
   83       -        raise IndexingConfigError()
   84       -
   85       -    try:
   86       -        db = await lancedb.connect_async(table_uri, storage_options=_storage_options())
   87       -    except Exception as exc:
   88       -        log.warning(
   89       -            "delete_stale_chunks: connect failed table_uri=%s cause=%s: %s",
   90       -            table_uri,
   91       -            type(exc).__name__,
   92       -            exc,
   93       -        )
   94       -        raise DeleteChunksTransientError(
   95       -            cause=f"lancedb connect failed: {type(exc).__name__}: {exc}"
   96       -        ) from exc
   97       -
   98       -    try:
   99       -        table = await db.open_table(INDEX_TABLE_NAME)
  100       -
  101       -        deleted = len(files)
  102       -        query = build_delete_query(files)
  103       -
  104       -        await table.delete(query)
  105       -
  106       -    except DeleteChunksError:
  107       -        raise
  108       -    except Exception as exc:
  109       -        log.warning(
  110       -            "delete_stale_chunks: delete failed table_uri=%s files=%d cause=%s: %s",
  111       -            table_uri,
  112       -            len(files),
  113       -            type(exc).__name__,
  114       -            exc,
  115       -        )
  116       -        raise DeleteChunksTransientError(
  117       -            cause=f"lancedb delete failed: {type(exc).__name__}: {exc}"
  118       -        ) from exc
  119       -
  120       -    log.info(
  121       -        "delete_stale_chunks: ok table_uri=%s files=%d deleted=%d",
  122       -        table_uri,
  123       -        len(files),
  124       -        deleted,
  125       -    )
  126       -    return deleted
  127       -
  128       -
  129       -__all__ = ["deleteStaleChunksStep"]

```
