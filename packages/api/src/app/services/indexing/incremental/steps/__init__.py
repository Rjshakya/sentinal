"""Step modules for the incremental indexing pipeline.

Three steps plus a best-effort teardown:

1. :func:`deleteStaleChunksStep` — host-side LanceDB delete of the
   ``removed + modified`` files' chunks (no sandbox).
2. :func:`ensureIncrementalSandbox` — create a fresh E2B index
   sandbox (only when there are files to append).
3. :func:`uploadIncrementalScripts` — upload ``chunking.py`` (shared)
   + ``incremental_ingestion.py`` (this package's ``scripts/``).
4. :func:`runIncrementalIngest` — append chunks for ``index_files``
   in one in-sandbox command + rebuild the FTS index.

Plus the best-effort teardown :func:`stopIndexerSandbox` (from the
full-index pipeline) at the end of the workflow.

The DBOS step names are unique across modules (they never collide
with the full-index pipeline's camelCase ``ensureIndexSandbox`` /
``runIndexPipeline`` etc.).

Shared with the full-index pipeline, imported as-is: ``getRepoUrl``,
``gitCloneToSandbox``, ``stopIndexerSandbox``, ``connect_index_sandbox``,
``create_index_run_step`` / ``mark_index_run_*_step``,
``mark_repo_indexed_success_step``, ``resolve_index_env``.
"""

from __future__ import annotations

from app.services.indexing.incremental.steps.delete_stale_chunks import (
    deleteStaleChunksStep,
)
from app.services.indexing.incremental.steps.ensure_sandbox import (
    ensureIncrementalSandbox,
)
from app.services.indexing.incremental.steps.run_incremental_ingest import (
    build_incremental_ingest_command,
    check_incremental_ingest_result,
    runIncrementalIngest,
)
from app.services.indexing.incremental.steps.upload_scripts import (
    build_incremental_scripts_args,
    uploadIncrementalScripts,
)

__all__ = [
    "build_incremental_ingest_command",
    "build_incremental_scripts_args",
    "check_incremental_ingest_result",
    "deleteStaleChunksStep",
    "ensureIncrementalSandbox",
    "runIncrementalIngest",
    "uploadIncrementalScripts",
]
