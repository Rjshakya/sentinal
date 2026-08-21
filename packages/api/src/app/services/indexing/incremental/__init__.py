"""The incremental indexing pipeline: reconcile pushes against LanceDB.

Triggered by GitHub ``push`` webhook deliveries on the repo's default
branch (see :func:`handle_push_event`). For each eligible push the
durable :func:`incrementalIndexRepo` workflow:

1. Host-side deletes the ``removed + modified`` files' chunks from the
   repo's S3-backed LanceDB dataset (no sandbox needed).
2. When there are files to append (``added + modified``), spins up a
   **fresh** index sandbox, clones at the default branch, and runs the
   in-sandbox :mod:`~app.services.indexing.incremental.scripts.incremental_ingestion`
   append script — chunking only the changed files and rebuilding the
   FTS index.

Public surface:

- :func:`handle_push_event` — the webhook adapter (router calls it).
- :func:`incrementalIndexRepo` — the DBOS durable workflow.
- :mod:`app.services.indexing.incremental.helpers` — pure, testable
  helpers (push classification, file aggregation, workflow id, delete
  predicates).
- :mod:`app.services.indexing.incremental.scripts` — the in-sandbox
  append script (uploaded as a file; not imported on the host).
"""

from __future__ import annotations

from app.services.indexing.incremental.types import (
    IncrementalIndexContext,
    IncrementalIndexRunResult,
    IncrementalIndexWorkflowInput,
    PushFileSet,
)
from app.services.indexing.incremental.webhook import (
    PushWebhookAck,
    handle_push_event,
)
from app.services.indexing.incremental.workflow import incrementalIndexRepo

__all__ = [
    "IncrementalIndexContext",
    "IncrementalIndexRunResult",
    "IncrementalIndexWorkflowInput",
    "PushFileSet",
    "PushWebhookAck",
    "handle_push_event",
    "incrementalIndexRepo",
]
