### packages/api/src/app/services/indexing/incremental/scripts/incremental_ingestion.py

```diff

deleted file mode 100644
index b64dd5a..0000000
--- a/packages/api/src/app/services/indexing/incremental/scripts/incremental_ingestion.py
+++ /dev/null
@@ -1,184 +0,0 @@
    2       -#!/usr/bin/env python3
    3       -"""In-sandbox incremental ingestion: append chunks for a file list.
    4       -
    5       -Uploaded as-is into the indexing sandbox by
    6       -``uploadIncrementalScripts`` (alongside the shared ``chunking.py``)
    7       -and invoked as the DBOS step's shell command. The host never imports
    8       -this file; it only ships it as bytes.
    9       -
   10       -Run as: ``python3 incremental_ingestion.py <repo_dir> --files <rel1> <rel2> ...``
   11       -
   12       -Differs from the full-index ``ingestion.py`` in exactly two ways:
   13       -
   14       -- **Append-only**: the repo's ``context`` table must already exist
   15       -  (a full index created it); this script opens it and calls
   16       -  ``table.add`` — never ``create_table(mode="overwrite")``.
   17       -- **File-scoped**: only the given repo-relative paths are chunked, so
   18       -  a push reconciling a handful of files does not re-chunk the repo.
   19       -
   20       -The FTS index is rebuilt with ``replace=True`` after the append, which
   21       -also repairs any drift left by the host-side delete.
   22       -
   23       -Required env:
   24       -- LANCEDB_TABLE_URI
   25       -- OPENAI_API_KEY
   26       -
   27       -Optional env:
   28       -- LANCEDB_BATCH_SIZE (default 50)
   29       -- AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY / AWS_REGION /
   30       -  AWS_ENDPOINT_URL (for ``s3://`` URIs)
   31       -"""
   32       -
   33       -from __future__ import annotations
   34       -
   35       -import argparse
   36       -import os
   37       -import sys
   38       -from collections.abc import Iterator
   39       -from pathlib import Path
   40       -
   41       -import lancedb  # type: ignore[reportMissingImports]
   42       -from lancedb.embeddings import (  # type: ignore[reportMissingImports]
   43       -    get_registry,
   44       -)
   45       -from lancedb.pydantic import LanceModel, Vector  # type: ignore[reportMissingImports]
   46       -
   47       -sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
   48       -from chunking import (  # type: ignore[reportMissingImports]
   49       -    DEFAULT_BATCH_SIZE,
   50       -    LANGUAGE_MAP,
   51       -    MAX_FILE_BYTES,
   52       -    chunk_one_file,
   53       -)
   54       -
   55       -INDEX_TABLE_NAME = "context"
   56       -EMBEDDING_MODEL = "text-embedding-3-large"
   57       -OPENAI_API_KEY_VAR = "openai_api_key"
   58       -
   59       -embedding_model = get_registry().get("openai").create(name=EMBEDDING_MODEL)
   60       -
   61       -
   62       -class CodeChunks(LanceModel):
   63       -    vector: Vector(embedding_model.ndims()) = embedding_model.VectorField()
   64       -    content: str = embedding_model.SourceField()
   65       -    file_name: str
   66       -    language: str
   67       -    start_line: int
   68       -    end_line: int
   69       -    node_types: str
   70       -
   71       -
   72       -def chunk_to_codeChunk(chunk) -> dict:
   73       -    return {
   74       -        "file_name": chunk.file_name,
   75       -        "language": chunk.language,
   76       -        "start_line": chunk.start_line,
   77       -        "end_line": chunk.end_line,
   78       -        "node_types": ", ".join(map(str, chunk.node_types)),
   79       -        "content": chunk.content,
   80       -    }
   81       -
   82       -
   83       -def _safe_rel_path(repo_root: Path, rel: str) -> Path | None:
   84       -    """Resolve a repo-relative path, rejecting any traversal outside the repo."""
   85       -    normalized = rel.replace("\\", "/").lstrip("/")
   86       -    candidate = (repo_root / normalized).resolve()
   87       -    try:
   88       -        candidate.relative_to(repo_root)
   89       -    except ValueError:
   90       -        return None
   91       -    return candidate
   92       -
   93       -
   94       -def iter_chunks_for_files(
   95       -    repo_dir: str,
   96       -    files: list[str],
   97       -    *,
   98       -    batch_size: int = DEFAULT_BATCH_SIZE,
   99       -) -> Iterator[list]:
  100       -    """Yield batches of chunks for the given repo-relative paths only.
  101       -
  102       -    Mirrors :func:`chunking.iter_chunks`' yield semantics (batch-full,
  103       -    file-complete, trailing partial) but walks the explicit file list
  104       -    instead of the whole tree. Files that are unsupported, missing, or
  105       -    too large are silently skipped.
  106       -    """
  107       -    root = Path(repo_dir).resolve()
  108       -    buffer: list = []
  109       -
  110       -    for rel in files:
  111       -        filepath = _safe_rel_path(root, rel)
  112       -        if filepath is None:
  113       -            continue
  114       -        ext = filepath.suffix
  115       -        language = LANGUAGE_MAP.get(ext)
  116       -        if language is None:
  117       -            continue
  118       -        try:
  119       -            if not filepath.is_file() or filepath.stat().st_size > MAX_FILE_BYTES:
  120       -                continue
  121       -            source = filepath.read_text(encoding="utf-8", errors="ignore")
  122       -        except OSError:
  123       -            continue
  124       -        if not source.strip():
  125       -            continue
  126       -        for chunk in chunk_one_file(filepath, language, source, root):
  127       -            buffer.append(chunk)
  128       -            if len(buffer) >= batch_size:
  129       -                yield buffer
  130       -                buffer = []
  131       -
  132       -    if buffer:
  133       -        yield buffer
  134       -
  135       -
  136       -def main(argv: list[str] | None = None) -> int:
  137       -    parser = argparse.ArgumentParser(
  138       -        description="Append chunks for a file list to the repo's LanceDB table."
  139       -    )
  140       -    parser.add_argument("repo_dir", help="Checked-out repo root inside the sandbox.")
  141       -    parser.add_argument(
  142       -        "--files",
  143       -        nargs="+",
  144       -        required=True,
  145       -        help="Repo-root-relative paths to index (added + modified).",
  146       -    )
  147       -    args = parser.parse_args(argv)
  148       -
  149       -    if not args.files:
  150       -        print("no files to index")
  151       -        return 0
  152       -
  153       -    batch_size = int(os.environ.get("LANCEDB_BATCH_SIZE") or DEFAULT_BATCH_SIZE)
  154       -
  155       -    db = lancedb.connect(
  156       -        os.environ["LANCEDB_TABLE_URI"],
  157       -        storage_options={
  158       -            "endpoint": os.environ["AWS_ENDPOINT_URL"],
  159       -            "region": os.environ["AWS_REGION"],
  160       -            "access_key_id": os.environ["AWS_ACCESS_KEY_ID"],
  161       -            "secret_access_key": os.environ["AWS_SECRET_ACCESS_KEY"],
  162       -        },
  163       -    )
  164       -
  165       -    table = db.open_table(INDEX_TABLE_NAME)
  166       -
  167       -    total_chunks = 0
  168       -    files_indexed: set[str] = set()
  169       -
  170       -    for batch in iter_chunks_for_files(
  171       -        args.repo_dir, args.files, batch_size=batch_size
  172       -    ):
  173       -        records = [chunk_to_codeChunk(c) for c in batch]
  174       -        table.add(records)
  175       -        total_chunks += len(batch)
  176       -        files_indexed.update(c.file_name for c in batch)
  177       -
  178       -    table.optimize()
  179       -
  180       -    print(f"indexed {total_chunks} chunks from {len(files_indexed)} files")
  181       -    return 0
  182       -
  183       -
  184       -if __name__ == "__main__":
  185       -    sys.exit(main())

```
