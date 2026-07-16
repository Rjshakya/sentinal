"""In-sandbox indexing entrypoint.

Run inside the E2B sandbox after the repo has been cloned. This
script:

1. Walks the cloned repo and chunks each source file via
   ``tree_sitter_language_pack.process()`` (in ``chunking.py``).
2. Pushes the chunks into a per-repo LanceDB table; the ``vector``
   column is auto-computed and stored by LanceDB via the OpenAI
   embedding function registered in ``embedding.py`` (the
   ``text-embedding-3-large`` model).
3. Builds a full-text search index over ``content`` so the table
   supports hybrid (vector + BM25) search.

Arguments (from ``argv``)::

    --repo-path  Absolute path to the cloned repo inside the sandbox.
    --repo-name  Repo name; used as the LanceDB table-name suffix.

Configuration is read from environment variables injected by the
orchestrator at command-execution time via ``sandbox.execute(envs=...)``::

    OPENAI_API_KEY   OpenAI key for the embedding model.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import uuid

import lancedb
from chunking import chunks_batch  # pyright: ignore[reportMissingImports]
from embedding import model  # pyright: ignore[reportMissingImports]
from lancedb.index import FTS
from lancedb.pydantic import LanceModel, Vector

from utils import lance_path, scripts_path, table_name  # pyright: ignore[reportMissingImports]

log = logging.getLogger(__name__)

sys.path.insert(0, scripts_path())


class CodeChunkModel(LanceModel):
    id: str
    file_name: str
    start_line: int
    end_line: int
    language: str
    node_types: str
    content: str = model.SourceField()
    vector: Vector(model.ndims()) = model.VectorField()  # pyright: ignore


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Ingest a cloned repo into a per-repo LanceDB table."
    )
    parser.add_argument(
        "--repo-path",
        required=True,
        help="Absolute path to the cloned repo inside the sandbox.",
    )
    parser.add_argument(
        "--repo-name",
        required=True,
        help="Repo name; used as the table-name suffix.",
    )
    return parser.parse_args()


async def ingest_repo(*, repo_path: str, repo_name: str, db_uri: str) -> None:
    try:
        db = await lancedb.connect_async(db_uri)
        table = await db.create_table(
            table_name(repo_name), exist_ok=True, schema=CodeChunkModel
        )

        for batch in chunks_batch(repo_path=repo_path, batch_size=100, chunk_size=1000):
            rows = [
                {
                    "id": str(uuid.uuid4()),
                    "file_name": chunk.file_name,
                    "start_line": chunk.start_line,
                    "end_line": chunk.end_line,
                    "language": chunk.language,
                    "node_types": ";".join(chunk.node_types),
                    "content": chunk.content,
                }
                for chunk in batch
            ]
            await table.add(rows)

        await table.create_index(
            "content", replace=True, config=FTS(with_position=True)
        )

        await table.optimize()

    except Exception as e:
        log.error(f"failed to ingest repo:{repo_name}, error:{e}")
        raise e


async def main() -> int:
    args = _parse_args()
    try:
        await ingest_repo(
            repo_path=args.repo_path, repo_name=args.repo_name, db_uri=lance_path()
        )
        return 0
    except Exception as e:
        print(f"{args.repo_name}:ingestion:error:{type(e).__name__}: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
