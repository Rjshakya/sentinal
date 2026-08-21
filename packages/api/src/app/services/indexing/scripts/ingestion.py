#!/usr/bin/env python3
"""In-sandbox ingestion: chunking generator -> LanceDB.

Uploaded as-is into the indexing sandbox by ``uploadScriptsToSandbox`` and
invoked as the DBOS step's shell command. The host never imports this
file; it only ships it as bytes.

Run as: ``python3 ingestion.py <repo_dir>``.

Required env:
- LANCEDB_TABLE_URI
- OPENAI_API_KEY

Optional env:
- LANCEDB_BATCH_SIZE (default 50)
- AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY / AWS_REGION /
  AWS_ENDPOINT_URL (for ``s3://`` URIs)
"""

from __future__ import annotations

import os
import sys

import lancedb  # type: ignore[reportMissingImports]
from lancedb.embeddings import (  # type: ignore[reportMissingImports]
    get_registry,
)
from lancedb.pydantic import LanceModel, Vector

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from chunking import iter_chunks  # type: ignore[reportMissingImports]

INDEX_TABLE_NAME = "context"
EMBEDDING_MODEL = "text-embedding-3-large"
OPENAI_API_KEY_VAR = "openai_api_key"
VECTOR_COLUMN = "vector"
SOURCE_COLUMN = "content"

DEFAULT_BATCH_SIZE = 50


embedding_model = get_registry().get("openai").create(name=EMBEDDING_MODEL)


class CodeChunks(LanceModel):
    vector: Vector(embedding_model.ndims()) = embedding_model.VectorField()
    content: str = embedding_model.SourceField()
    file_name: str
    language: str
    start_line: int
    end_line: int
    node_types: str


def chunk_to_codeChunk(chunk) -> dict:
    return {
        "file_name": chunk.file_name,
        "language": chunk.language,
        "start_line": chunk.start_line,
        "end_line": chunk.end_line,
        "node_types": ", ".join(map(str, chunk.node_types)),
        "content": chunk.content,
    }


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: ingestion.py <repo_dir>", file=sys.stderr)
        return 2

    repo_dir = sys.argv[1]
    batch_size = int(os.environ["LANCEDB_BATCH_SIZE"])

    if batch_size is None:
        batch_size = DEFAULT_BATCH_SIZE

    db = lancedb.connect(
        os.environ["LANCEDB_TABLE_URI"],
        storage_options={
            "endpoint": os.environ["AWS_ENDPOINT_URL"],
            "region": os.environ["AWS_REGION"],
            "access_key_id": os.environ["AWS_ACCESS_KEY_ID"],
            "secret_access_key": os.environ["AWS_SECRET_ACCESS_KEY"],
        },
    )

    table = db.create_table(INDEX_TABLE_NAME, schema=CodeChunks, mode="overwrite")

    total_chunks = 0
    files: set[str] = set()

    for batch in iter_chunks(repo_dir, batch_size=batch_size):
        records = [chunk_to_codeChunk(c) for c in batch]
        table.add(records)
        total_chunks += len(batch)
        files.update(c.file_name for c in batch)

    table.create_fts_index("content", replace=True)

    print(f"indexed {total_chunks} chunks from {len(files)} files")
    return 0


if __name__ == "__main__":
    sys.exit(main())
