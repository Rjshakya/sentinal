"""The search service.

Plain async, no DBOS — search is a stateless read against a remote
object-store-backed LanceDB dataset, so the durable-workflow machinery
would add no value (matches the precedent of
:func:`app.routers.users.list_my_repos`).

The flow:

1. Gate on :attr:`Settings.indexing_configured` — raises
   :class:`SearchConfigError` (-> 503).
2. Open an :class:`AsyncSession` and look up the
   :class:`app.models.repo.Repo` row by
   ``(user_id, repo_owner, repo_name)``. Missing → 404
   :class:`SearchRepoNotFoundError`; ``is_indexed=False`` → 400
   :class:`SearchNotIndexedError`.
3. ``lancedb.connect_async(uri, storage_options=...)`` then
   ``await db.open_table("context")`` (the table name is constant;
   every repo's dataset has a single ``"context"`` table — see
   :mod:`app.services.indexing.scripts.ingestion`).
4. ``await table.search(query, query_type="hybrid")`` then
   ``await q.limit(limit).to_list()``. The query-time embedding
   function is reconstructed by LanceDB from the dataset's metadata
   (the in-sandbox ingestion script stored it with the ``CodeChunks``
   schema), so the host needs no embedding setup of its own; the
   embedding call — including LanceDB's retry backoff — runs on the
   library's dedicated executor thread, never on the event loop.
5. Project every row to a :class:`CodeSearchResultOut`.

Every LanceDB call is wrapped in a try/except that re-raises as
:class:`SearchTableError` (-> 502) so the router can map a single
HTTP status regardless of the underlying cause.
"""

from __future__ import annotations

import logging
import os
import time

import lancedb
from lancedb.rerankers import RRFReranker

from app.core.config import settings
from app.services.search.errors import (
    SearchConfigError,
    SearchError,
    SearchTableError,
)
from app.services.search.helpers import build_table_uri, parse_node_types
from app.services.search.types import (
    CodeSearchRequest,
    CodeSearchResponse,
    CodeSearchResultOut,
)

os.environ["OPENAI_API_KEY"] = settings.openai_api_key

log = logging.getLogger(__name__)

INDEX_TABLE_NAME: str = "context"


def _check_config() -> None:
    """Final gate: search is only meaningful when the indexing stack is configured."""
    if not settings.indexing_configured:
        raise SearchConfigError(
            detail=(
                "Search requires OPENAI_API_KEY, INDEX_S3_BUCKET, "
                "AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_REGION "
                "and AWS_ENDPOINT_URL to be set on the API server."
            )
        )


def _storage_options() -> dict[str, str]:
    """S3-compatible storage options forwarded to LanceDB."""
    return {
        "endpoint": settings.aws_endpoint_url,
        "region": settings.aws_region,
        "access_key_id": settings.aws_access_key_id,
        "secret_access_key": settings.aws_secret_access_key,
    }


def _table_uri(*, owner: str, repo: str) -> str:
    """S3 URI of the repo's LanceDB dataset."""
    return build_table_uri(
        bucket=settings.index_s3_bucket,
        prefix=settings.index_s3_prefix,
        owner=owner,
        repo=repo,
    )


def _row_to_result(row: dict) -> CodeSearchResultOut:
    """Project one LanceDB row to a :class:`CodeSearchResultOut`."""
    file_name = str(row.get("file_name") or "")
    language = str(row.get("language") or "")
    start_line = int(row.get("start_line") or 0)
    end_line = int(row.get("end_line") or 0)
    content = str(row.get("content") or "")
    node_types = parse_node_types(row.get("node_types"))
    raw_score = row.get("_relevance_score", row.get("_score", 0.0))
    try:
        score = float(raw_score)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        score = 0.0
    return CodeSearchResultOut(
        file_name=file_name,
        language=language,
        start_line=start_line,
        end_line=end_line,
        node_types=node_types,
        content=content,
        _relevance_score=score,
    )


async def run_search(*, user_id: str, request: CodeSearchRequest) -> CodeSearchResponse:
    """Execute one search against the caller's indexed repo.

    Public entry point. Performs the config gate, the ownership +
    indexed-flag check, opens the LanceDB dataset, runs the hybrid
    query, and projects the response. Logs a single structured line
    per call with the latency and result count.
    """
    _check_config()

    started = time.perf_counter()

    try:
        db = await lancedb.connect_async(
            _table_uri(owner=request.owner, repo=request.repo),
            storage_options=_storage_options(),
        )
        table = await db.open_table(INDEX_TABLE_NAME)
        reranker = RRFReranker()

        q = await table.search(
            request.query,
            query_type="hybrid",
        )

        rows = await q.rerank(reranker=reranker).limit(request.limit).to_list()
    except SearchError:
        raise
    except Exception as exc:
        log.warning(
            "search: lancedb failed owner=%s repo=%s  cause=%s: %s",
            request.owner,
            request.repo,
            type(exc).__name__,
            exc,
        )
        raise SearchTableError(cause=f"{type(exc).__name__}: {exc}") from exc

    results = [_row_to_result(row) for row in rows]
    elapsed_ms = (time.perf_counter() - started) * 1000.0

    log.info(
        "search: ok owner=%s repo=%s  query_len=%d limit=%d "
        "result_count=%d elapsed_ms=%.1f",
        request.owner,
        request.repo,
        len(request.query),
        request.limit,
        len(results),
        elapsed_ms,
    )

    return CodeSearchResponse(
        owner=request.owner,
        repo=request.repo,
        query=request.query,
        results=results,
    )


__all__ = ["run_search"]
