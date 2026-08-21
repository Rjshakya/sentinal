"""The indexing pipeline: tree-sitter chunking in the sandbox,
LanceDB ingest + S3 persistence inside the same sandbox.

Public surface:

- :func:`indexRepo` -- the DBOS durable workflow (dispatch with the
  deterministic id from
  :func:`app.services.indexing.helpers.index_workflow_id`).
- :mod:`app.services.indexing.helpers` -- pure, testable helpers
  (repo URL parsing, table URI build, summary-line parser).
- :mod:`app.services.indexing.scripts` -- the in-sandbox chunking
  generator + LanceDB writer (uploaded as files; not imported on
  the host).
"""

from __future__ import annotations

from app.services.indexing.types import (
    IndexContext,
    IndexRunResult,
    IndexWorkflowInput,
)
from app.services.indexing.workflow import indexRepo

__all__ = [
    "IndexContext",
    "IndexRunResult",
    "IndexWorkflowInput",
    "indexRepo",
]
