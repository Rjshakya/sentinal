# Sentinel Code Graph CLI

[![PyPI version](https://img.shields.io/pypi/v/sentinel-codegraph)](https://pypi.org/project/sentinel-codegraph/)

Async CLI that scans a directory or file, extracts structural nodes
(files, classes, functions, methods, interfaces, types, imports) and
edges (contains, imports, calls) with raw tree-sitter, and stores them
in Ladybug (embedded property graph, zero setup).

- Default database is a known-location Ladybug file
  (`~/.codegraph/graph.lbdb`), so query time never guesses where the
  index lives. Pass `--db` to any command to override it.
- `--db :memory:` indexes ephemerally (lost when the process exits).
- Scope: **Python, TypeScript/JavaScript, Go**. (`queries.py` stays on
  disk, unwired.)
- One database holds exactly one index: `--overwrite` flushes the
  whole db first, so re-indexing is idempotent. Re-indexing an
  already-indexed tree *without* `--overwrite` aborts with a
  duplicate primary-key error — one tree, one DB, one `--overwrite`.
- `--no-persist` dry-runs the pipeline (parse → nodes → edges → print,
  no DB writes).

## Install

From PyPI (users, sandboxes, agents — provides the `codegraph` command):

```powershell
pip install sentinel-codegraph==0.3.0
```

Project pages: [PyPI](https://pypi.org/project/sentinel-codegraph/) ·
[TestPyPI](https://test.pypi.org/project/sentinel-codegraph/)

From source (workspace development, latest pinned deps in `uv.lock`):

```powershell
uv sync
```

## Usage

Run from the repo root (paths below are repo-root-relative):

```powershell
# index a tree into the default DB (re-runnable; --overwrite flushes first)
codegraph index ./packages/api/src --overwrite

# index a single file (root = its parent dir; must be a supported language)
codegraph index ./packages/api/main.py

# inspect the database
codegraph stats

# index and print the hierarchy tree of the indexed root
codegraph index ./packages/codegraph/src --output tree

# dump every collected node (kind, lines, parent, children, callees)
codegraph index ./packages/codegraph/src --output nodes

# list every calls edge (caller -> callee, implementation order)
codegraph index ./packages/codegraph/src --output calls

# dry-run: print without persisting
codegraph index ./packages/codegraph/src --no-persist --output tree

# Ephemeral index (no file written)
codegraph index ./packages/codegraph/src --db :memory: --output tree

# explore the index (read-only; works from anywhere — default DB is known)
codegraph query overview
codegraph query files
codegraph query search --name reviewWorkflowV2
codegraph query --json callees --name reviewWorkflowV2
```

`--db`, `--root`, and `--json` are `query`-level flags: they come
before the verb (`codegraph query --db <path> --json <verb> …`).

## Flow

`amain` parses args, then three linear stages in `pipeline.py`:

```
read(target) -> build_graph(root, items) -> out(db, root, graph, ...)
```

- **read** — discover (`walk`: suffix → language, prune noise dirs,
  skip oversize/undecodable) + read off the loop → `ScannedSources(root,
  items)`. I/O.
- **build_graph** — pure, two passes: (1) collect — `parse_file_input`
  per file (blank source or unsupported language → skip, counted)
  into nodes + `contains` / `imports` plus buffered call sites; (2)
  link — `resolve_call_edges` joins sites against the `(file, name)`
  definition registry + per-file import maps (alias-aware, joined on
  a single candidate: the defining-module original when the import
  carries one, else the bound name; Go dot-imported files are a
  fallback) into `calls` with real node ids, dropping unresolvable
  sites. Merge → `BuiltGraph(root, files, skipped, nodes, edges)`.
  No I/O, no DB.
- **out** — persist (`create_all`, `clear_all` when `--overwrite`,
  `add_all`) then print (`summary` | `tree` | `nodes` | `calls`) →
  `IndexResult`. I/O.

`cli.py` holds only arg parsing + `amain` wiring + `run_stats` /
`run_query`; `__main__.py` calls `cli.main()`.

## Python emitter

Each Python file is walked once (`collect_python_file`):
`Node` + `Edge(CONTAINS)` with `base:name:start:end` ids for defs,
`Node(IMPORT)` + `Edge(IMPORTS)` per imported name (keeping the
`as`-alias original, e.g. `from utils import helper as h` records bound
`h` + original `helper`), and bare-name calls buffered unresolved with
their call-site line. The link phase then joins each site — same-file
hit first, else the import map's resolved file + original name — into
`calls` edges with real node ids. Absolute imports tolerate a
root-relative prefix on indexed paths (`src/app/…` satisfies
`import app.…`). Builtins, stdlib, third-party, star-import calls,
attribute calls (`obj.method(…)`, `self.x(…)`), and module-level call
sites yield no edges. Decorator applications (`@retry`,
`@with_logging(…)`) buffer as call sites on the decorated def/class
with the @-line and resolve like ordinary calls (attribute decorators
such as `@app.get(…)` are skipped). A class decorator makes the class
the caller, so `calls` edges may target a class. One edge per
caller → callee pair, each stamped with its call-site line. Calls
render in implementation order, not alphabetical.

## TypeScript / JavaScript collector

Each TS/JS file is walked once (`collect_ts_file`): classes,
functions, methods, interfaces, type aliases, and arrow-bound consts
(`export` wrappers are transparent) → `Node` + `Edge(CONTAINS)`;
imports keep alias originals (`import {a as b}` → bound `b` +
original `a`; default imports join on the bound name); bare calls and
`new C()` constructions buffer unresolved. Relative specifiers resolve
with extension + `/index` fallbacks; bare (npm) specifiers never
resolve. Member calls (`obj.m()`), builtins, and module-level sites
yield no edges.

## Go collector

Each Go file is walked once (`collect_go_file`): funcs, methods
(reparented to their receiver struct when same-file), struct types →
`class`, interface types → `interface` (with `method_elem` children as
methods), other named types → `type`. Blank imports bind `*`, dot
imports bind `.` (their target files are searched for otherwise
unresolved bare sites). Import tails match indexed `.go` stems;
selector calls (`pkg.Fn()`), builtins, and package-level sites yield
no edges.

## Schema (Ladybug)

- `CodeNode`: `id (PK), root, file_path, kind (file|class|function|method|interface|type|import),
  name, language, start_line, end_line, parent_id, is_placeholder`
- `Contains` / `Imports` / `Calls`: rels between `CodeNode` rows
  (`target_module` on `Imports`, `site_line` on `Calls`).

`site_line` is the 1-based call-site line inside the caller (`Calls`
rels only; `NULL` = unknown). Callees sort by it.

## Node ids (all languages)

- file node: `base` (path anchored at the CLI root, e.g. `workflows/review.py`)
- def node: `base:name:start:end` (e.g. `workflows/review.py:helper:10:15`)
- import node: `base:import:<name>:<line>`

Every stored `Calls` edge points at real node ids — unresolvable call
sites are dropped at build time, so no placeholder rows exist
(`is_placeholder` stays on the schema for old databases only).
Querier's check:

```cypher
// 1. file's nodes (find the caller)
MATCH (f:CodeNode {id: '<file>'})-[:Contains]->(n) RETURN n;
// 2. caller's callees, in implementation order
MATCH (c:CodeNode {id: '<caller id>'})-[e:Calls]->(d) RETURN d ORDER BY e.site_line;
```

Tables are created with `create_all` (`IF NOT EXISTS`): after a
schema change, delete the `.lbdb` file **and its sidecars**
(`.lbdb.wal`, `.lbdb.wal.checkpoint`) and re-index — a stale WAL
poisons the fresh open with a corruption error.

## Querying (agent ladder)

The `query` verbs are read-only and built for agents that don't know
node id shapes — every step returns the ids the next step needs:

1. `query overview` — what's indexed (counts by kind/edge/language).
2. `query files` — rel paths (a file node id *is* its rel path).
3. `query search --name <fragment> [--kind …] [--file …] [--limit N]` —
   substring-match def names → full rows with ids. Zero hits and
   truncation (`truncated: true`) tell the agent to rephrase/narrow.
4. `query node|callees|callers|children --id <id>` (or `--name` exact +
   optional `--file`; ambiguity is an error listing hits) and
   `query imports --file <rel>` — drill down; new names chain back
   to `search`.

`--root` narrows to one indexed root (default: all), `--json` emits
the stable chaining envelope
(`{root, verb, count, truncated, items[]}` with
`{id, kind, name, file_path, language, start_line, end_line,
parent_id}` plus `site_line` on calls items and `target_module` on
imports items). `overview --json` is the exception: it returns a
counts object (`files/nodes/edges/by_kind/by_edge/by_language`),
not the row envelope. `search` is a case-insensitive substring over
def names and never matches file nodes (use `files` for those).
Exit codes: `0` on success even with zero hits (`count: 0` says so);
`1` on resolution errors (unknown id, no/ambiguous name, bad
`--limit`) or a never-indexed database (hint printed, no empty
result); `2` on CLI misuse. Read paths never create
files or directories (only `index` persistence creates
`~/.codegraph/`).

## Module map

- `cli.py` — arg parsing, `amain` wiring (`read → build_graph → out`), `main`, `run_stats`, `run_query`
- `query.py` — pure exploration shaping: `search_nodes`, `exact_matches`, JSON envelope, human rendering
- `pipeline.py` — `read` / `build_graph` / `out`, `ScannedSources` / `BuiltGraph` / `IndexResult`, `OutputMode`, `print_tree` / `print_nodes` / `print_calls`
- `parser/__init__.py` — barrel: re-exports only, no logic
- `parser/rows.py` — `FileRows`, `build_file_rows`, `build_python_file_rows`
- `parser/links.py` — `ImportEntry`, `build_file_import_map`, `build_dot_import_targets`, `resolve_call_edges` (+ per-language module-specifier resolvers)
- `parser/lang_python.py` — Python collect phase (`collect_python_file`)
- `parser/lang_typescript.py` — TS/JS collect phase (`collect_ts_file`)
- `parser/lang_go.py` — Go collect phase (`collect_go_file`)
- `parser/queries.py` — kept, unwired
- `parser/base.py` — `ParsedFile` / `ParsedDefinition` / `ParsedImport` / `ParsedCall` IR types
- `parser/raw_core.py` — tree-sitter `parse`, `walk`, `span`, text helpers
- `models.py` — `Node` / `Edge` dataclasses (+ `NodeKind`, `EdgeKind`)
- `graph_store.py` — `LadybugStore` (UNWIND ingest, `clear_all`, `add_all`, count/list queries, narrow `get_node` / `callees` / `callers` / `children` / `file_imports` / `list_files` reads)
- `tree.py` — `GraphSnapshot`, `render_tree` (nesting by `contains`, calls in `site_line` order)
- `walk.py` — suffix → language discovery, noise-dir pruning
- `config.py` — `DEFAULT_DB` (`~/.codegraph/graph.lbdb`) + `--db` path resolution: file path or `:memory:` (`ResolvedDb`)
- `examples/dummy_tree.py` — tree-sitter parse demo (grammar probe);
  from `packages/codegraph/`: `python examples/dummy_tree.py
  --lang py|ts|go` prints the raw S-expression

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
- Ladybug is embedded: one `AsyncConnection` per store, and `out()`
  holds a single store from persist through the snapshot reads, so
  `:memory:` databases stay alive for the whole call.
- Calls are bare-name only (`name(…)`), alias-aware via the import
  map (`from utils import helper as h` + `h()` resolves to `helper`;
  TS `import {a as b}` + `b()` resolves to `a`; TS default imports
  join on the bound name; Go dot-imported files are a fallback);
  `new C()` in TS counts as a call. Attribute / member calls
  (`obj.method()`, `self.x()`, `pkg.Fn()`), builtins, stdlib,
  third-party, star-import calls, and module-level call sites yield
  no edges.
- Files with unsupported suffixes are discovered, then skipped
  (`(N skipped)` in the summary).

## Tests

```powershell
Set-Location packages/codegraph
uv run pytest tests
```
