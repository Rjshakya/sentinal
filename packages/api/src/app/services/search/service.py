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
3. Instantiate the OpenAI embedding function on the host. The
   in-sandbox ingestion step registered the same function with the
   dataset via the ``CodeChunks`` ``VectorField`` /
   ``SourceField`` definitions; LanceDB looks up the function by name
   at query time, so the host only needs to instantiate it with the
   same model name so it knows how to embed the query.
4. ``lancedb.connect(uri, storage_options=...)`` then
   ``db.open_table("context")`` (the table name is constant; every
   repo's dataset has a single ``"context"`` table — see
   :mod:`app.services.indexing.scripts.ingestion`).
5. ``table.search(query, query_type="hybrid").limit(limit).to_list()``.
6. Project every row to a :class:`CodeSearchResultOut`.

Every LanceDB call is wrapped in a try/except that re-raises as
:class:`SearchTableError` (-> 502) so the router can map a single
HTTP status regardless of the underlying cause.
"""

from __future__ import annotations

import logging
import time

import lancedb
from lancedb.embeddings import (
    EmbeddingFunction,
    get_registry,
)
from lancedb.query import LanceQueryBuilder
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.core.db import async_session_maker
from app.models.indexing import IndexRun, IndexRunState
from app.models.repo import Repo
from app.services.search.errors import (
    SearchConfigError,
    SearchError,
    SearchNotIndexedError,
    SearchRepoNotFoundError,
    SearchTableError,
)
from app.services.search.helpers import build_table_uri, parse_node_types
from app.services.search.types import (
    CodeSearchRequest,
    CodeSearchResponse,
    CodeSearchResultOut,
)

log = logging.getLogger(__name__)

INDEX_TABLE_NAME: str = "context"
EMBEDDING_MODEL_NAME: str = "text-embedding-3-large"


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


def _register_embedding_function() -> EmbeddingFunction:
    """Re-instantiate the OpenAI embedding function on the host.

    The dataset was built inside the indexing sandbox with the
    ``openai`` registry's ``text-embedding-3-large`` model. LanceDB
    persists the function name with the schema; when the host opens
    the table and calls ``search(query, query_type="hybrid")``,
    LanceDB looks the function up by name in its process-local
    registry, so this call is what makes the hybrid path work
    end-to-end from the API process.
    """
    return get_registry().get("openai").create(name=EMBEDDING_MODEL_NAME)


def _table_uri(*, owner: str, repo: str) -> str:
    """S3 URI of the repo's LanceDB dataset."""
    return build_table_uri(
        bucket=settings.index_s3_bucket,
        prefix=settings.index_s3_prefix,
        owner=owner,
        repo=repo,
    )


async def _resolve_repo_row(
    session: AsyncSession,
    *,
    user_id: str,
    owner: str,
    repo: str,
) -> Repo:
    """Return the :class:`Repo` row or raise the right :class:`SearchError`.

    Two distinct outcomes:

    - No row for this user + owner + name → :class:`SearchRepoNotFoundError`.
    - Row exists but no successful :class:`IndexRun` → :class:`SearchNotIndexedError`.

    The caller distinguishes these by HTTP status (404 vs 400). A
    successful ``IndexRun`` (state ``SUCCESS``) is the source of truth
    for "this repo's LanceDB dataset exists at the S3 URI" — the
    in-sandbox ingestion script writes the dataset on the success
    path, so a missing or non-terminal run means the dataset is
    either absent or stale.
    """
    stmt = select(Repo).where(
        Repo.user_id == user_id,
        Repo.repo_owner == owner,
        Repo.repo_name == repo,
        Repo.is_indexed == True,
    )
    row: Repo | None = (await session.exec(stmt)).first()
    if row is None:
        raise SearchRepoNotFoundError(user_id=user_id, owner=owner, repo=repo)

    indexed_stmt = (
        select(IndexRun.id)
        .where(
            IndexRun.user_id == user_id,
            IndexRun.repo_owner == owner,
            IndexRun.repo_name == repo,
            IndexRun.state == IndexRunState.SUCCESS,
        )
        .limit(1)
    )
    has_indexed_run = (await session.exec(indexed_stmt)).first() is not None
    if not has_indexed_run:
        raise SearchNotIndexedError(owner=owner, repo=repo)

    return row


def _build_query(
    *,
    table: lancedb.table.Table,  # type: ignore[name-defined]
    query: str,
    limit: int,
) -> LanceQueryBuilder:
    """Build the LanceDB query for the host-side hybrid search.

    The embedding function is instantiated at module call time
    (see :func:`_register_embedding_function`); passing
    ``query_type="hybrid"`` lets LanceDB combine the FTS index over
    ``content`` with the embedding-based vector search.
    """
    return table.search(query, query_type="hybrid").limit(limit)


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

    async with async_session_maker() as session:
        repo_row = await _resolve_repo_row(
            session,
            user_id=user_id,
            owner=request.owner,
            repo=request.repo,
        )
        repo_row_id = repo_row.id

    started = time.perf_counter()
    _register_embedding_function()

    try:
        db = lancedb.connect(
            _table_uri(owner=request.owner, repo=request.repo),
            storage_options=_storage_options(),
        )
        table = db.open_table(INDEX_TABLE_NAME)
        rows = _build_query(
            table=table, query=request.query, limit=request.limit
        ).to_list()
    except SearchError:
        raise
    except Exception as exc:
        log.warning(
            "search: lancedb failed owner=%s repo=%s repo_id=%s cause=%s: %s",
            request.owner,
            request.repo,
            repo_row_id,
            type(exc).__name__,
            exc,
        )
        raise SearchTableError(cause=f"{type(exc).__name__}: {exc}") from exc

    results = [_row_to_result(row) for row in rows]
    elapsed_ms = (time.perf_counter() - started) * 1000.0

    log.info(
        "search: ok owner=%s repo=%s repo_id=%s query_len=%d limit=%d "
        "result_count=%d elapsed_ms=%.1f",
        request.owner,
        request.repo,
        repo_row_id,
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
