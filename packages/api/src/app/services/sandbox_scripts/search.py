"""In-sandbox hybrid search over the per-repo LanceDB table.

Run inside the E2B sandbox after the repo has been indexed. Embeds
the query with the same OpenAI model used at ingestion, runs a
hybrid (vector + full-text) search against the per-repo table, and
emits the results on stdout as JSON.

The raw ``vector`` field is intentionally excluded from the
projection — search consumers only need the text, file location,
and metadata. Each result row is therefore a plain dict with the
following keys: ``id``, ``file_name``, ``start_line``, ``end_line``,
``content``, ``node_types``, ``language``.

Configuration is read from environment variables injected by the
orchestrator at command-execution time:

    OPENAI_API_KEY   (injected via sandbox.execute(envs=...))

Invocation::

    python search.py --repo-name <repo> --query "git clone flow" \\
                    [--limit 10] [--language python] [--file-prefix src/]

Output (stdout): a single JSON object::

    {
        "sandbox_id": "...",
        "repo_name":  "...",
        "query":      "...",
        "results":    [
            {"id": ..., "file_name": ..., "start_line": ...,
             "end_line": ..., "content": ..., "node_types": ...,
             "language": ...},
            ...
        ]
    }
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys

import lancedb
from embedding import create_embeddings  # pyright: ignore[reportMissingImports]
from lancedb.rerankers import RRFReranker

from utils import lance_path, scripts_path, table_name  # pyright: ignore[reportMissingImports]

log = logging.getLogger(__name__)

DEFAULT_LIMIT: int = 10

sys.path.insert(0, scripts_path())

_reranker = RRFReranker()


def _parse_args():
    parser = argparse.ArgumentParser(
        description="Hybrid search over the per-repo LanceDB table."
    )
    parser.add_argument(
        "--repo-name",
        required=True,
        help="Repo name; used as the table-name suffix.",
    )
    parser.add_argument("--query", required=True, help="The search query.")
    parser.add_argument(
        "--limit",
        type=int,
        default=DEFAULT_LIMIT,
        help=f"Max number of results (default: {DEFAULT_LIMIT}).",
    )
    parser.add_argument(
        "--language", default=None, help="Filter by language, e.g. 'python'."
    )
    parser.add_argument(
        "--file-prefix", default=None, help="Filter by file path prefix."
    )
    return parser.parse_args()


async def hybrid_search(
    *,
    query: str,
    repo_name: str,
    limit: int,
    language: str | None,
    file_prefix: str | None,
    db_uri: str = lance_path(),
) -> list[dict]:
    db = await lancedb.connect_async(db_uri)
    table = await db.open_table(table_name(repo_name))

    resp = await create_embeddings([query])
    query_vector = resp.data[0].embedding
    q = table.query().nearest_to(query_vector).nearest_to_text(query)

    # prefilter: narrows candidates BEFORE ranking, so a `limit`
    # of 10 doesn't get eaten by irrelevant-language matches
    filters = []
    if language:
        filters.append(f"language = '{language}'")
    if file_prefix:
        filters.append(f"file_name LIKE '{file_prefix}%'")
    if filters:
        q = q.where(" AND ".join(filters))

    rows: list[dict] = await (
        q.rerank(_reranker)
        .select(
            [
                "id",
                "file_name",
                "start_line",
                "end_line",
                "content",
                "node_types",
                "language",
            ]
        )
        .limit(limit)
        .to_list()
    )
    return rows


async def main() -> int:
    args = _parse_args()
    try:
        rows = await hybrid_search(
            query=args.query,
            repo_name=args.repo_name,
            limit=args.limit,
            language=args.language,
            file_prefix=args.file_prefix,
        )
    except Exception as e:
        log.error(f"search failed for repo={args.repo_name}: {e}")
        print(
            json.dumps(
                {
                    "repo_name": args.repo_name,
                    "query": args.query,
                    "error": str(e),
                    "type": type(e).__name__,
                }
            ),
            file=sys.stderr,
        )
        return 1

    print(
        json.dumps(
            {
                "repo_name": args.repo_name,
                "query": args.query,
                "results": rows,
            }
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
