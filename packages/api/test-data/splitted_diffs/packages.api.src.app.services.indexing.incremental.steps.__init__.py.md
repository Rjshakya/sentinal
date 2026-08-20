### packages/api/src/app/services/indexing/incremental/steps/__init__.py

```diff

deleted file mode 100644
index c03151b..0000000
--- a/packages/api/src/app/services/indexing/incremental/steps/__init__.py
+++ /dev/null
@@ -1,53 +0,0 @@
    2       -"""Step modules for the incremental indexing pipeline.
    3       -
    4       -Three steps plus a best-effort teardown:
    5       -
    6       -1. :func:`deleteStaleChunksStep` — host-side LanceDB delete of the
    7       -   ``removed + modified`` files' chunks (no sandbox).
    8       -2. :func:`ensureIncrementalSandbox` — create a fresh E2B index
    9       -   sandbox (only when there are files to append).
   10       -3. :func:`uploadIncrementalScripts` — upload ``chunking.py`` (shared)
   11       -   + ``incremental_ingestion.py`` (this package's ``scripts/``).
   12       -4. :func:`runIncrementalIngest` — append chunks for ``index_files``
   13       -   in one in-sandbox command + rebuild the FTS index.
   14       -
   15       -Plus the best-effort teardown :func:`stopIndexerSandbox` (from the
   16       -full-index pipeline) at the end of the workflow.
   17       -
   18       -The DBOS step names are unique across modules (they never collide
   19       -with the full-index pipeline's camelCase ``ensureIndexSandbox`` /
   20       -``runIndexPipeline`` etc.).
   21       -
   22       -Shared with the full-index pipeline, imported as-is: ``getRepoUrl``,
   23       -``gitCloneToSandbox``, ``stopIndexerSandbox``, ``connect_index_sandbox``,
   24       -``create_index_run_step`` / ``mark_index_run_*_step``,
   25       -``mark_repo_indexed_success_step``, ``resolve_index_env``.
   26       -"""
   27       -
   28       -from __future__ import annotations
   29       -
   30       -from app.services.indexing.incremental.steps.delete_stale_chunks import (
   31       -    deleteStaleChunksStep,
   32       -)
   33       -from app.services.indexing.incremental.steps.ensure_sandbox import (
   34       -    ensureIncrementalSandbox,
   35       -)
   36       -from app.services.indexing.incremental.steps.run_incremental_ingest import (
   37       -    build_incremental_ingest_command,
   38       -    check_incremental_ingest_result,
   39       -    runIncrementalIngest,
   40       -)
   41       -from app.services.indexing.incremental.steps.upload_scripts import (
   42       -    build_incremental_scripts_args,
   43       -    uploadIncrementalScripts,
   44       -)
   45       -
   46       -__all__ = [
   47       -    "build_incremental_ingest_command",
   48       -    "build_incremental_scripts_args",
   49       -    "check_incremental_ingest_result",
   50       -    "deleteStaleChunksStep",
   51       -    "ensureIncrementalSandbox",
   52       -    "runIncrementalIngest",
   53       -    "uploadIncrementalScripts",
   54       -]

```
