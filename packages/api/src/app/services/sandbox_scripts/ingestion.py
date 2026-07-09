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

Configuration is read from environment variables injected by the
orchestrator at command-execution time:

    REPO_PATH        (set by the orchestrator: /home/user/sentinel-workspace/<repo_name>)
    DATASET_NAME     (set by the orchestrator: <repo_name>; used as the table-name suffix)
    LANCEDB_URI      (default: /home/user/lance_data)
    OPENAI_API_KEY   (injected via sandbox.execute(envs=...))
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
import uuid

import lancedb
from chunking import chunks_batch
from embedding import model
from lancedb.index import FTS
from lancedb.pydantic import LanceModel, Vector

log = logging.getLogger(__name__)

REPO_PATH: str = os.environ.get("REPO_PATH", "/sentinel-workspace/repo")
REPO_NAME: str = os.environ.get("DATASET_NAME", "sentinel:repo:default")
LANCEDB_URI: str = os.environ.get("LANCEDB_URI", "/home/user/lance_data")

sys.path.insert(0, "/sentinel-workspace/context")


class CodeChunkModel(LanceModel):
    id: str
    file_name: str
    start_line: int
    end_line: int
    language: str
    node_types: str
    content: str = model.SourceField()
    vector: Vector(model.ndims()) = model.VectorField()  # pyright: ignore


async def ingest_repo(*, repo_path: str, repo_name: str, db_uri: str):
    try:
        db = await lancedb.connect_async(db_uri)
        table = await db.create_table(
            f"{repo_name}_table", exist_ok=True, schema=CodeChunkModel
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

        await table.create_index("content", replace=True, config=FTS())

    except Exception as e:
        log.error(f"failed to ingest repo:{repo_name}, error:{e}")
        raise e


async def main() -> int:
    try:
        await ingest_repo(repo_path=REPO_PATH, repo_name=REPO_NAME, db_uri=LANCEDB_URI)
        return 0
    except Exception as e:
        print(f"{REPO_NAME}:ingestion:error:{type(e).__name__}: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
