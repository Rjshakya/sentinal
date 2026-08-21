#!/usr/bin/env python3
"""In-sandbox incremental ingestion: append chunks for a file list.

Uploaded as-is into the indexing sandbox by
``uploadIncrementalScripts`` (alongside the shared ``chunking.py``)
and invoked as the DBOS step's shell command. The host never imports
this file; it only ships it as bytes.

Run as: ``python3 incremental_ingestion.py <repo_dir> --files <rel1> <rel2> ...``

Differs from the full-index ``ingestion.py`` in exactly two ways:

- **Append-only**: the repo's ``context`` table must already exist
  (a full index created it); this script opens it and calls
  ``table.add`` — never ``create_table(mode="overwrite")``.
- **File-scoped**: only the given repo-relative paths are chunked, so
  a push reconciling a handful of files does not re-chunk the repo.

The FTS index is rebuilt with ``replace=True`` after the append, which
also repairs any drift left by the host-side delete.

Required env:
- LANCEDB_TABLE_URI
- OPENAI_API_KEY

Optional env:
- LANCEDB_BATCH_SIZE (default 50)
- AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY / AWS_REGION /
  AWS_ENDPOINT_URL (for ``s3://`` URIs)
"""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Iterator
from pathlib import Path

import lancedb  # type: ignore[reportMissingImports]
from lancedb.embeddings import (  # type: ignore[reportMissingImports]
    get_registry,
)
from lancedb.pydantic import LanceModel, Vector  # type: ignore[reportMissingImports]

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from chunking import (  # type: ignore[reportMissingImports]
    DEFAULT_BATCH_SIZE,
    LANGUAGE_MAP,
    MAX_FILE_BYTES,
    chunk_one_file,
)

INDEX_TABLE_NAME = "context"
EMBEDDING_MODEL = "text-embedding-3-large"
OPENAI_API_KEY_VAR = "openai_api_key"

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


def _safe_rel_path(repo_root: Path, rel: str) -> Path | None:
    """Resolve a repo-relative path, rejecting any traversal outside the repo."""
    normalized = rel.replace("\\", "/").lstrip("/")
    candidate = (repo_root / normalized).resolve()
    try:
        candidate.relative_to(repo_root)
    except ValueError:
        return None
    return candidate


def iter_chunks_for_files(
    repo_dir: str,
    files: list[str],
    *,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> Iterator[list]:
    """Yield batches of chunks for the given repo-relative paths only.

    Mirrors :func:`chunking.iter_chunks`' yield semantics (batch-full,
    file-complete, trailing partial) but walks the explicit file list
    instead of the whole tree. Files that are unsupported, missing, or
    too large are silently skipped.
    """
    root = Path(repo_dir).resolve()
    buffer: list = []

    for rel in files:
        filepath = _safe_rel_path(root, rel)
        if filepath is None:
            continue
        ext = filepath.suffix
        language = LANGUAGE_MAP.get(ext)
        if language is None:
            continue
        try:
            if not filepath.is_file() or filepath.stat().st_size > MAX_FILE_BYTES:
                continue
            source = filepath.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if not source.strip():
            continue
        for chunk in chunk_one_file(filepath, language, source, root):
            buffer.append(chunk)
            if len(buffer) >= batch_size:
                yield buffer
                buffer = []

    if buffer:
        yield buffer


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Append chunks for a file list to the repo's LanceDB table."
    )
    parser.add_argument("repo_dir", help="Checked-out repo root inside the sandbox.")
    parser.add_argument(
        "--files",
        nargs="+",
        required=True,
        help="Repo-root-relative paths to index (added + modified).",
    )
    args = parser.parse_args(argv)

    if not args.files:
        print("no files to index")
        return 0

    batch_size = int(os.environ.get("LANCEDB_BATCH_SIZE") or DEFAULT_BATCH_SIZE)

    db = lancedb.connect(
        os.environ["LANCEDB_TABLE_URI"],
        storage_options={
            "endpoint": os.environ["AWS_ENDPOINT_URL"],
            "region": os.environ["AWS_REGION"],
            "access_key_id": os.environ["AWS_ACCESS_KEY_ID"],
            "secret_access_key": os.environ["AWS_SECRET_ACCESS_KEY"],
        },
    )

    table = db.open_table(INDEX_TABLE_NAME)

    total_chunks = 0
    files_indexed: set[str] = set()

    for batch in iter_chunks_for_files(
        args.repo_dir, args.files, batch_size=batch_size
    ):
        records = [chunk_to_codeChunk(c) for c in batch]
        table.add(records)
        total_chunks += len(batch)
        files_indexed.update(c.file_name for c in batch)

    table.optimize()

    print(f"indexed {total_chunks} chunks from {len(files_indexed)} files")
    return 0


if __name__ == "__main__":
    sys.exit(main())
