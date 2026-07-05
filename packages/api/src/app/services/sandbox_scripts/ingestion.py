"""In-sandbox indexing entrypoint.

Run inside the Daytona sandbox after the repo has been cloned. This
script:

1. Walks the cloned repo and chunks each source file via
   ``tree_sitter_language_pack.process()`` (in ``tree_sitter.py``).
2. Pipes the chunked text into Cognee via ``cognee.add`` and builds
   the knowledge graph via ``cognee.cognify``.

Configuration is read from environment variables injected by the
orchestrator at sandbox creation time:

    LLM_PROVIDER, LLM_MODEL, LLM_API_KEY
    EMBEDDING_PROVIDER, EMBEDDING_MODEL, EMBEDDING_DIMENSIONS, EMBEDDING_API_KEY
    DATASET_NAME          (set by the orchestrator: sentinel:repo:owner/name)
"""

from __future__ import annotations

import asyncio
import os
import sys

from dotenv import load_dotenv

load_dotenv()

import cognee
from chunking import ChunkedRepo, FileChunk, chunk_repo
from cognee.api.v1.add.add import DataItem

REPO_PATH: str = os.environ.get("REPO_PATH", "/workspace/repo")
REPO_NAME: str = os.environ.get("DATASET_NAME", "sentinel:repo:default")

sys.path.insert(0, "/workspace")

CODE_REPO_PROMPT = """
You are analyzing a chunk of source code from a software repository, not natural
language prose. Extract entities as code constructs — functions, classes, methods,
imports, and modules — and relationships as code semantics: calls, inherits_from,
imports, defines, references. Do not extract narrative entities like people or
places unless they appear literally in comments or docstrings.
"""


def chunk_to_data_item(*, file_name: str, chunk: FileChunk) -> DataItem:
    # composite key -> deterministic UUID (stable across re-ingestion runs)
    key = f"{file_name}:chunk:{chunk.start_line}-{chunk.end_line}"

    return DataItem(
        data=chunk.content,  # raw text, ingested directly as text content
        label=key,  # human-readable, not required to be unique but keep it that way anyway
        external_metadata={
            "file_name": file_name,
            "start_line": chunk.start_line,
            "end_line": chunk.end_line,
            "language": chunk.language,
            "size_bytes": chunk.size_bytes,
        },
    )


def convert_chunk_repo_to_data_items_repo(chunked_repo: ChunkedRepo) -> list[DataItem]:

    items: list[DataItem] = []

    for file_name, file_chunk in chunked_repo.root.items():
        for chunk in file_chunk:
            data_item = chunk_to_data_item(file_name=file_name, chunk=chunk)
            items.append(data_item)

    return items


async def ingest_repo(*, repo_path: str, repo_name: str):

    await cognee.forget(everything=True)

    chunked_repo = chunk_repo(repo_path=repo_path, chunk_size=900)
    data = convert_chunk_repo_to_data_items_repo(chunked_repo)
    result = await cognee.remember(
        data,
        repo_name,
        incremental_loading=True,
        custom_prompt=CODE_REPO_PROMPT,
    )

    if result.error:
        print(f"{repo_name}:ingestion:error:{result.error}")

    print(f"{repo_name}:ingestion:started")


async def main() -> int:

    try:
        await ingest_repo(repo_path=REPO_PATH, repo_name=REPO_NAME)
        return 0
    except Exception as e:
        print(f"{REPO_NAME}:ingestion:error:{type(e).__name__}: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
