# Sentinel Code Graph CLI

Async CLI that scans a directory or file, extracts structural nodes
(files, classes, functions, imports) and edges (contains, imports)
with tree-sitter, and stores them in SQL.

- Default database is a local SQLite file (zero setup).
- `--db postgresql+asyncpg://…` targets Postgres with the same schema.
- v1 scope: **Python + TypeScript/JavaScript**, structure only
  (no call edges, no cross-file resolution).

## Install

From the repo root (workspace member, latest pinned deps in `uv.lock`):

```powershell
uv sync
```

## Usage

```powershell
# index a tree (re-runnable; --overwrite replaces this root's rows)
uv run --package codegraph python -m codegraph.cli index ./packages/api/src --db ./codegraph.db --overwrite

# index a single file (root = its parent dir)
uv run --package codegraph python -m codegraph.cli index ./web/src/lib/api.ts --db ./codegraph.db

# inspect the database
uv run --package codegraph python -m codegraph.cli stats --db ./codegraph.db

# index and print the hierarchy tree of the indexed root
uv run --package codegraph python -m codegraph.cli index ./src --db ./codegraph.db --output tree

# dump every collected node (kind, lines, parent, children, callees)
uv run --package codegraph python -m codegraph.cli index ./src --db ./codegraph.db --output nodes

# Postgres instead of SQLite
uv run --package codegraph python -m codegraph.cli index ./src --db postgresql+asyncpg://postgres:postgres@localhost:5432/aicode
```

## Schema

- `codegraph_node`: `id, root, file_path, kind (file|class|function|import), name,
  language, start_line, end_line, parent_id, created_at`
- `codegraph_edge`: `id, root, src_id, dst_id, kind (contains|imports|calls),
  target_module, created_at`

`calls` edges are caller → callee, derived purely from the tree-sitter
structure hierarchy: a definition nested in a function is that
function's callee. Methods (nested in a class) are excluded — they
render under their class. Call *sites* in bodies are not extracted;
only nested definitions.

`root` is the normalised absolute scan root, so one database can hold
many repos and re-indexing a root is idempotent.

## Design notes

- Parsing uses `tree_sitter_language_pack.process(structure=True,
  imports=True)` — the pack's high-level API. Raw `Node` iteration is
  deliberately avoided: it segfaults nondeterministically on Windows
  (py-tree-sitter 0.26). Import *names* are recovered from the
  statement source text in pure Python.
- Parsing runs on the event-loop thread (tree-sitter objects are not
  thread-safe); only file I/O goes through `asyncio.to_thread`.
- SQLite uses `NullPool`: pooled aiosqlite connections race the GC on
  Windows. The CLI is sequential, so pooling buys nothing.
- Known v1 limitations: anonymous `function() {}` expressions assigned
  to variables are not surfaced by the pack's structure rows; TS import
  aliases resolve to the original name when the pack omits them.

## Tests

```powershell
uv run --package codegraph pytest tests
```
