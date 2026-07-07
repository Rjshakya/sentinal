from __future__ import annotations

import logging

from chunking import FileChunk, chunks_batch
from openai import AsyncClient

log = logging.getLogger(__name__)

client = AsyncClient()


async def create_embeddings(input: list[str]):
    return await client.embeddings.create(input=input, model="text-embedding-3-large")


def create_embedding_input(chunk: FileChunk) -> str:
    return f"# language: {chunk.language}\n# file: {chunk.file_name}\n content: {chunk.content}"


async def create_repo_embeddings(*, repo_path: str, batch_size: int, chunk_size: int):

    for batch in chunks_batch(
        repo_path=repo_path, batch_size=batch_size, chunk_size=chunk_size
    ):
        embedding_input: list[str] = []
        for file_chunk in batch:
            result = create_embedding_input(file_chunk)
            embedding_input.append(result)
        try:
            embeddings = await create_embeddings(embedding_input)
        except Exception as e:
            log.warning(
                f"Failed to create embedding of batch (size={len(embedding_input)}); "
                f"dropping {len(embedding_input)} chunks: {e}"
            )
            continue
        yield (embeddings.data, batch)
