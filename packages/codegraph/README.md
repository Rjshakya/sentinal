# Sentinel Code Graph CLI

Async CLI that scans a directory or file, extracts structural nodes
(files, classes, functions, methods, imports) and edges (contains,
imports, calls) with raw tree-sitter, and stores them in SQL.

- Default database is a local SQLite file (zero setup).
- `--db postgresql+asyncpg://…` targets Postgres with the same schema.
- Scope: **Python only**. (`lang_go.py`, `lang_typescript.py`, and
  `queries.py` stay on disk, unwired, for re-integration.)
- One database holds exactly one index: `--overwrite` flushes the
  whole db first, so re-indexing is idempotent.
- `--no-persist` dry-runs the pipeline (parse → nodes → edges → print,
  no DB writes).

## Install

From the repo root (workspace member, latest pinned deps in `uv.lock`):

```powershell
uv sync
```

## Usage

```powershell
# index a tree (re-runnable; --overwrite flushes the whole db first)
uv run --package codegraph python -m codegraph.cli index ./packages/api/src --db ./codegraph.db --overwrite

# index a single file (root = its parent dir; must be Python)
uv run --package codegraph python -m codegraph.cli index ./packages/api/main.py --db ./codegraph.db

# inspect the database
uv run --package codegraph python -m codegraph.cli stats --db ./codegraph.db

# index and print the hierarchy tree of the indexed root
uv run --package codegraph python -m codegraph.cli index ./src --db ./codegraph.db --output tree

# dump every collected node (kind, lines, parent, children, callees)
uv run --package codegraph python -m codegraph.cli index ./src --db ./codegraph.db --output nodes

# list every calls edge (caller -> callee, implementation order)
uv run --package codegraph python -m codegraph.cli index ./src --db ./codegraph.db --output calls

# dry-run: print without persisting
uv run --package codegraph python -m codegraph.cli index ./src --no-persist --output tree

# Postgres instead of SQLite
uv run --package codegraph python -m codegraph.cli index ./src --db postgresql+asyncpg://postgres:postgres@localhost:5432/aicode
```

## Flow

`amain` parses args, then three linear stages in `pipeline.py`:

```
read(target) -> build_graph(root, items) -> out(db, root, graph, ...)
```

- **read** — discover (`walk`: suffix → language, prune noise dirs,
  skip oversize/undecodable) + read off the loop → `ScannedSources(root,
  items)`. I/O.
- **build_graph** — pure: frozen import index over rel paths, then
  `parse_file_input` per file (blank source or non-Python → skip,
  counted), merge node/edge lists → `BuiltGraph(root, files, skipped,
  nodes, edges)`. No I/O, no DB.
- **out** — persist (`create_all`, `clear_all` when `--overwrite`,
  `add_all`) then print (`summary` | `tree` | `nodes` | `calls`) →
  `IndexResult`. I/O.

`cli.py` holds only arg parsing + `amain` wiring + `run_stats`;
`__main__.py` calls `cli.main()`.

## Python emitter

Each Python file is walked once (`extract_nodes_and_edges`):
`Node` + `Edge(CONTAINS)` with `base:name:start:end` ids for defs,
`Node(IMPORT)` + `Edge(IMPORTS)` per imported name, and bare-name calls
buffered then flushed — same-file hit by name first, else assumed
`base:name` edge via the frozen import index (relative imports
absolutized against the importer, longest-suffix fallback for
above-root packages). Builtins, stdlib, third-party, attribute calls
(`obj.method(…)`, `self.x(…)`), and module-level call sites yield no
edges. One edge per caller → callee pair (first site wins), each stamped
with its call-site line. Calls render in implementation order, not
alphabetical.

## Schema

- `codegraph_node`: `id, root, file_path, kind (file|class|function|method|import),
  name, language, start_line, end_line, parent_id, created_at`
- `codegraph_edge`: `id, root, src_id, dst_id, kind (contains|imports|calls),
  target_module, site_line, created_at`

`site_line` is the 1-based call-site line inside the caller (`calls`
edges only; `NULL` = unknown). Callees sort by it.

## Node ids (Python v2)

- file node: `base` (path anchored at the CLI root, e.g. `workflows/review.py`)
- def node: `base:name:start:end` (e.g. `workflows/review.py:helper:10:15`)
- assumed callee ref: `base:name` (lines unknowable per file)

`Edge.dst_id` carries no foreign key by design: an assumed ref whose
target is missing dangles, and that miss *is* the broken-import signal.
Querier's check:

```sql
-- 1. file's nodes (find the caller)
SELECT * FROM codegraph_edge WHERE src_id = '<file>' AND kind = 'contains';
-- 2. caller's callees, in implementation order
SELECT * FROM codegraph_edge WHERE src_id = '<caller id>' AND kind = 'calls' ORDER BY site_line;
-- 3. for each callee id: SELECT * FROM codegraph_node WHERE id = '<callee>';
--    miss on the (base, name) lookup => broken import/call.
```

Tables are created with `create_all`, which never migrates: after a
schema change, delete the `.db` file and re-index.

## Module map

- `cli.py` — arg parsing, `amain` wiring (`read → build_graph → out`), `main`, `run_stats`
- `pipeline.py` — `read` / `build_graph` / `out`, `ScannedSources` / `BuiltGraph` / `IndexResult`, `OutputMode`, `print_tree` / `print_nodes` / `print_calls`
- `parser/__init__.py` — barrel: re-exports only, no logic
- `parser/rows.py` — `FileRows`, `build_file_rows`, `build_python_file_rows`
- `parser/links.py` — `build_import_index`, `resolve_call_edges` (+ module-specifier resolvers)
- `parser/lang_python.py` — v2 single-pass emitter (`extract_nodes_and_edges`)
- `parser/lang_go.py`, `parser/lang_typescript.py`, `parser/queries.py` — kept, unwired (Python-only for now)
- `parser/base.py` — `ParsedFile` / `ParsedDefinition` / `ParsedImport` / `ParsedCall` IR types
- `parser/raw_core.py` — tree-sitter `parse`, `walk`, `span`, text helpers
- `models.py` — `Node` / `Edge` SQLModel tables (+ `NodeKind`, `EdgeKind`)
- `store.py` — async engine, `clear_all`, `add_all`, count/list queries
- `tree.py` — `GraphSnapshot`, `render_tree` (nesting by `contains`, calls in `site_line` order)
- `walk.py` — suffix → language discovery, noise-dir pruning
- `config.py` — `--db` URL resolution (`ResolvedDb`)

## Design notes

- Pipeline is functional: `read -> build_graph -> out`. Extractors and
  builders are pure; I/O lives only at the edge (discover + read,
  persist, print).
- Build output is a simple flat graph: `BuiltGraph` carries merged
  `nodes` + `edges` tuples only. Every consumer (persist, snapshot,
  printers) derives what it needs from those two lists.
- Graph values are frozen dataclasses holding tuples — immutable
  snapshots, safe to share between build and out.
- Parsing uses raw `tree_sitter_language_pack.get_parser().parse()`.
  Import *names* are recovered from the statement source text in pure
  Python.
- Parsing runs on the event-loop thread (tree-sitter objects are not
  thread-safe); only file I/O goes through `asyncio.to_thread`.
- SQLite uses `NullPool`: pooled aiosqlite connections race the GC on
  Windows. The CLI is sequential, so pooling buys nothing.
- Calls are bare-name only (`name(…)`); attribute calls
  (`obj.method()`, `self.x()`, `pkg.Fn()`), builtins, stdlib,
  third-party, and module-level call sites yield no edges.
- Non-Python files are discovered, then skipped (`(N skipped)` in the
  summary) — the e2e test asserts exactly that gate.

## Tests

```powershell
uv run --package codegraph pytest tests
```
