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

    LANCEDB_URI      (default: /home/user/lance_data)
    OPENAI_API_KEY   (injected via sandbox.execute(envs=...))

Invocation::

    python search.py --sandbox-id <id> --repo-name <repo> \\
                    --query "git clone flow" [--limit 10]

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
import os
import sys

import lancedb
from embedding import create_embeddings

log = logging.getLogger(__name__)

LANCEDB_URI: str = os.environ.get("LANCEDB_URI", "/home/user/lance_data")
DEFAULT_LIMIT: int = 10

sys.path.insert(0, "/sentinel-workspace/context")


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
    return parser.parse_args()


async def hybrid_search(*, query: str, repo_name: str, limit: int) -> list[dict]:
    db = await lancedb.connect_async(LANCEDB_URI)
    table = await db.open_table(f"{repo_name}_table")

    resp = await create_embeddings([query])
    query_vector = resp.data[0].embedding

    rows: list[dict] = await (
        table.query()
        .nearest_to(query_vector)
        .nearest_to_text(query)
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
