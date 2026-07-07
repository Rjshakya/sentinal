"""In-sandbox indexing entrypoint.

Run inside the E2B sandbox after the repo has been cloned. This
script:

1. Walks the cloned repo and chunks each source file via
   ``tree_sitter_language_pack.process()`` (in ``chunking.py``).
2. Batches the chunks (100 at a time) and embeds them with the
   OpenAI ``text-embedding-3-large`` model.
3. Persists the chunks + vectors to a per-repo LanceDB table at
   ``LANCEDB_URI`` (default: ``/home/user/lance_data``).

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
from chunking import FileChunk
from embedding import create_repo_embeddings
from lancedb.pydantic import LanceModel
from openai.types.embedding import Embedding

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
    vector: list[float]


async def connect_lance_db(connection_str: str):
    return await lancedb.connect_async(connection_str)


def create_code_chunk_obj(*, embedding: Embedding, chunk: FileChunk):
    obj = CodeChunkModel(
        id=str(uuid.uuid4()),
        file_name=chunk.file_name,
        start_line=chunk.start_line,
        end_line=chunk.end_line,
        language=chunk.language,
        node_types=";".join(chunk.node_types),
        vector=embedding.embedding,
    )
    return obj


async def ingest_repo(*, repo_path: str, repo_name: str, db_uri: str):

    try:
        db = await connect_lance_db(db_uri)
        table = await db.create_table(
            f"{repo_name}_table", exist_ok=True, schema=CodeChunkModel
        )

        async for embeddings, batch in create_repo_embeddings(
            repo_path=repo_path, batch_size=100, chunk_size=1000
        ):
            data: list[CodeChunkModel] = []

            for file_chunk, embedding in zip(batch, embeddings):
                code_chunk_obj = create_code_chunk_obj(
                    embedding=embedding, chunk=file_chunk
                )
                data.append(code_chunk_obj)

            await table.add(data)

        await table.create_index("vector", replace=True)

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
