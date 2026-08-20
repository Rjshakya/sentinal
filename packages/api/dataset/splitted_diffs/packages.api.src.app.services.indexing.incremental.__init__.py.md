### packages/api/src/app/services/indexing/incremental/__init__.py

```diff

deleted file mode 100644
index 82733f5..0000000
--- a/packages/api/src/app/services/indexing/incremental/__init__.py
+++ /dev/null
@@ -1,48 +0,0 @@
    2       -"""The incremental indexing pipeline: reconcile pushes against LanceDB.
    3       -
    4       -Triggered by GitHub ``push`` webhook deliveries on the repo's default
    5       -branch (see :func:`handle_push_event`). For each eligible push the
    6       -durable :func:`incrementalIndexRepo` workflow:
    7       -
    8       -1. Host-side deletes the ``removed + modified`` files' chunks from the
    9       -   repo's S3-backed LanceDB dataset (no sandbox needed).
   10       -2. When there are files to append (``added + modified``), spins up a
   11       -   **fresh** index sandbox, clones at the default branch, and runs the
   12       -   in-sandbox :mod:`~app.services.indexing.incremental.scripts.incremental_ingestion`
   13       -   append script — chunking only the changed files and rebuilding the
   14       -   FTS index.
   15       -
   16       -Public surface:
   17       -
   18       -- :func:`handle_push_event` — the webhook adapter (router calls it).
   19       -- :func:`incrementalIndexRepo` — the DBOS durable workflow.
   20       -- :mod:`app.services.indexing.incremental.helpers` — pure, testable
   21       -  helpers (push classification, file aggregation, workflow id, delete
   22       -  predicates).
   23       -- :mod:`app.services.indexing.incremental.scripts` — the in-sandbox
   24       -  append script (uploaded as a file; not imported on the host).
   25       -"""
   26       -
   27       -from __future__ import annotations
   28       -
   29       -from app.services.indexing.incremental.types import (
   30       -    IncrementalIndexContext,
   31       -    IncrementalIndexRunResult,
   32       -    IncrementalIndexWorkflowInput,
   33       -    PushFileSet,
   34       -)
   35       -from app.services.indexing.incremental.webhook import (
   36       -    PushWebhookAck,
   37       -    handle_push_event,
   38       -)
   39       -from app.services.indexing.incremental.workflow import incrementalIndexRepo
   40       -
   41       -__all__ = [
   42       -    "IncrementalIndexContext",
   43       -    "IncrementalIndexRunResult",
   44       -    "IncrementalIndexWorkflowInput",
   45       -    "PushFileSet",
   46       -    "PushWebhookAck",
   47       -    "handle_push_event",
   48       -    "incrementalIndexRepo",
   49       -]

```
