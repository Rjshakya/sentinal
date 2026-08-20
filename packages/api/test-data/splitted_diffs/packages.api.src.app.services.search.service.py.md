### packages/api/src/app/services/search/service.py

```diff

index ed691e4..8949ec6 100644
--- a/packages/api/src/app/services/search/service.py
+++ b/packages/api/src/app/services/search/service.py
@@ -14,18 +14,18 @@ The flow:
   15    15     ``(user_id, repo_owner, repo_name)``. Missing → 404
   16    16     :class:`SearchRepoNotFoundError`; ``is_indexed=False`` → 400
   17    17     :class:`SearchNotIndexedError`.
   18       -3. ``lancedb.connect_async(uri, storage_options=...)`` then
   19       -   ``await db.open_table("context")`` (the table name is constant;
   20       -   every repo's dataset has a single ``"context"`` table — see
         18 +3. Instantiate the OpenAI embedding function on the host. The
         19 +   in-sandbox ingestion step registered the same function with the
         20 +   dataset via the ``CodeChunks`` ``VectorField`` /
         21 +   ``SourceField`` definitions; LanceDB looks up the function by name
         22 +   at query time, so the host only needs to instantiate it with the
         23 +   same model name so it knows how to embed the query.
         24 +4. ``lancedb.connect(uri, storage_options=...)`` then
         25 +   ``db.open_table("context")`` (the table name is constant; every
         26 +   repo's dataset has a single ``"context"`` table — see
   21    27     :mod:`app.services.indexing.scripts.ingestion`).
   22       -4. ``await table.search(query, query_type="hybrid")`` then
   23       -   ``await q.limit(limit).to_list()``. The query-time embedding
   24       -   function is reconstructed by LanceDB from the dataset's metadata
   25       -   (the in-sandbox ingestion script stored it with the ``CodeChunks``
   26       -   schema), so the host needs no embedding setup of its own; the
   27       -   embedding call — including LanceDB's retry backoff — runs on the
   28       -   library's dedicated executor thread, never on the event loop.
   29       -5. Project every row to a :class:`CodeSearchResultOut`.
         28 +5. ``table.search(query, query_type="hybrid").limit(limit).to_list()``.
         29 +6. Project every row to a :class:`CodeSearchResultOut`.
   30    30  
   31    31  Every LanceDB call is wrapped in a try/except that re-raises as
   32    32  :class:`SearchTableError` (-> 502) so the router can map a single
@@ -35,16 +35,26 @@ HTTP status regardless of the underlying cause.
   36    36  from __future__ import annotations
   37    37  
   38    38  import logging
   39       -import os
   40    39  import time
   41    40  
   42    41  import lancedb
   43       -from lancedb.rerankers import RRFReranker
         42 +from lancedb.embeddings import (
         43 +    EmbeddingFunction,
         44 +    get_registry,
         45 +)
         46 +from lancedb.query import LanceQueryBuilder
         47 +from sqlmodel import select
         48 +from sqlmodel.ext.asyncio.session import AsyncSession
   44    49  
   45    50  from app.core.config import settings
         51 +from app.core.db import async_session_maker
         52 +from app.models.indexing import IndexRun, IndexRunState
         53 +from app.models.repo import Repo
   46    54  from app.services.search.errors import (
   47    55      SearchConfigError,
   48    56      SearchError,
         57 +    SearchNotIndexedError,
         58 +    SearchRepoNotFoundError,
   49    59      SearchTableError,
   50    60  )
   51    61  from app.services.search.helpers import build_table_uri, parse_node_types
@@ -54,11 +64,10 @@ from app.services.search.types import (
   55    65      CodeSearchResultOut,
   56    66  )
   57    67  
   58       -os.environ["OPENAI_API_KEY"] = settings.openai_api_key
   59       -
   60    68  log = logging.getLogger(__name__)
   61    69  
   62    70  INDEX_TABLE_NAME: str = "context"
         71 +EMBEDDING_MODEL_NAME: str = "text-embedding-3-large"
   63    72  
   64    73  
   65    74  def _check_config() -> None:
@@ -83,6 +92,20 @@ def _storage_options() -> dict[str, str]:
   84    93      }
   85    94  
   86    95  
         96 +def _register_embedding_function() -> EmbeddingFunction:
         97 +    """Re-instantiate the OpenAI embedding function on the host.
         98 +
         99 +    The dataset was built inside the indexing sandbox with the
        100 +    ``openai`` registry's ``text-embedding-3-large`` model. LanceDB
        101 +    persists the function name with the schema; when the host opens
        102 +    the table and calls ``search(query, query_type="hybrid")``,
        103 +    LanceDB looks the function up by name in its process-local
        104 +    registry, so this call is what makes the hybrid path work
        105 +    end-to-end from the API process.
        106 +    """
        107 +    return get_registry().get("openai").create(name=EMBEDDING_MODEL_NAME)
        108 +
        109 +
   87   110  def _table_uri(*, owner: str, repo: str) -> str:
   88   111      """S3 URI of the repo's LanceDB dataset."""
   89   112      return build_table_uri(
@@ -93,6 +116,70 @@ def _table_uri(*, owner: str, repo: str) -> str:
   94   117      )
   95   118  
   96   119  
        120 +async def _resolve_repo_row(
        121 +    session: AsyncSession,
        122 +    *,
        123 +    user_id: str,
        124 +    owner: str,
        125 +    repo: str,
        126 +) -> Repo:
        127 +    """Return the :class:`Repo` row or raise the right :class:`SearchError`.
        128 +
        129 +    Two distinct outcomes:
        130 +
        131 +    - No row for this user + owner + name → :class:`SearchRepoNotFoundError`.
        132 +    - Row exists but no successful :class:`IndexRun` → :class:`SearchNotIndexedError`.
        133 +
        134 +    The caller distinguishes these by HTTP status (404 vs 400). A
        135 +    successful ``IndexRun`` (state ``SUCCESS``) is the source of truth
        136 +    for "this repo's LanceDB dataset exists at the S3 URI" — the
        137 +    in-sandbox ingestion script writes the dataset on the success
        138 +    path, so a missing or non-terminal run means the dataset is
        139 +    either absent or stale.
        140 +    """
        141 +    stmt = select(Repo).where(
        142 +        Repo.user_id == user_id,
        143 +        Repo.repo_owner == owner,
        144 +        Repo.repo_name == repo,
        145 +        Repo.is_indexed == True,
        146 +    )
        147 +    row: Repo | None = (await session.exec(stmt)).first()
        148 +    if row is None:
        149 +        raise SearchRepoNotFoundError(user_id=user_id, owner=owner, repo=repo)
        150 +
        151 +    indexed_stmt = (
        152 +        select(IndexRun.id)
        153 +        .where(
        154 +            IndexRun.user_id == user_id,
        155 +            IndexRun.repo_owner == owner,
        156 +            IndexRun.repo_name == repo,
        157 +            IndexRun.state == IndexRunState.SUCCESS,
        158 +        )
        159 +        .limit(1)
        160 +    )
        161 +    has_indexed_run = (await session.exec(indexed_stmt)).first() is not None
        162 +    if not has_indexed_run:
        163 +        raise SearchNotIndexedError(owner=owner, repo=repo)
        164 +
        165 +    return row
        166 +
        167 +
        168 +def _build_query(
        169 +    *,
        170 +    table: lancedb.table.Table,  # type: ignore[name-defined]
        171 +    query: str,
        172 +    limit: int,
        173 +) -> LanceQueryBuilder:
        174 +    """Build the LanceDB query for the host-side hybrid search.
        175 +
        176 +    The embedding function is instantiated at module call time
        177 +    (see :func:`_register_embedding_function`); passing
        178 +    ``query_type="hybrid"`` lets LanceDB combine the FTS index over
        179 +    ``content`` with the embedding-based vector search.
        180 +    """
        181 +    return table.search(query, query_type="hybrid").limit(limit)
        182 +
        183 +
   97   184  def _row_to_result(row: dict) -> CodeSearchResultOut:
   98   185      """Project one LanceDB row to a :class:`CodeSearchResultOut`."""
   99   186      file_name = str(row.get("file_name") or "")
@@ -127,29 +214,35 @@ async def run_search(*, user_id: str, request: CodeSearchRequest) -> CodeSearchR
  128   215      """
  129   216      _check_config()
  130   217  
        218 +    async with async_session_maker() as session:
        219 +        repo_row = await _resolve_repo_row(
        220 +            session,
        221 +            user_id=user_id,
        222 +            owner=request.owner,
        223 +            repo=request.repo,
        224 +        )
        225 +        repo_row_id = repo_row.id
        226 +
  131   227      started = time.perf_counter()
        228 +    _register_embedding_function()
  132   229  
  133   230      try:
  134       -        db = await lancedb.connect_async(
        231 +        db = lancedb.connect(
  135   232              _table_uri(owner=request.owner, repo=request.repo),
  136   233              storage_options=_storage_options(),
  137   234          )
  138       -        table = await db.open_table(INDEX_TABLE_NAME)
  139       -        reranker = RRFReranker()
  140       -
  141       -        q = await table.search(
  142       -            request.query,
  143       -            query_type="hybrid",
  144       -        )
  145       -
  146       -        rows = await q.rerank(reranker=reranker).limit(request.limit).to_list()
        235 +        table = db.open_table(INDEX_TABLE_NAME)
        236 +        rows = _build_query(
        237 +            table=table, query=request.query, limit=request.limit
        238 +        ).to_list()
  147   239      except SearchError:
  148   240          raise
  149   241      except Exception as exc:
  150   242          log.warning(
  151       -            "search: lancedb failed owner=%s repo=%s  cause=%s: %s",
        243 +            "search: lancedb failed owner=%s repo=%s repo_id=%s cause=%s: %s",
  152   244              request.owner,
  153   245              request.repo,
        246 +            repo_row_id,
  154   247              type(exc).__name__,
  155   248              exc,
  156   249          )
@@ -159,10 +252,11 @@ async def run_search(*, user_id: str, request: CodeSearchRequest) -> CodeSearchR
  160   253      elapsed_ms = (time.perf_counter() - started) * 1000.0
  161   254  
  162   255      log.info(
  163       -        "search: ok owner=%s repo=%s  query_len=%d limit=%d "
        256 +        "search: ok owner=%s repo=%s repo_id=%s query_len=%d limit=%d "
  164   257          "result_count=%d elapsed_ms=%.1f",
  165   258          request.owner,
  166   259          request.repo,
        260 +        repo_row_id,
  167   261          len(request.query),
  168   262          request.limit,
  169   263          len(results),

```
