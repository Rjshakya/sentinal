"""Typed step errors for the incremental indexing pipeline.

Reuses the full-index hierarchy from
:mod:`app.services.indexing.errors` (the marker base
:class:`TransientIndexingError` + the ``_should_retry_index``
predicate) so every ``@DBOS.step`` in this pipeline applies the same
retry policy:

    should_retry=_should_retry_index

New variants only where the incremental path adds failure modes that
the full index cannot hit:

- :class:`DeleteChunksError` / :class:`DeleteChunksTransientError` —
  the host-side LanceDB delete step.
- :class:`IncrementalIngestError` / :class:`IncrementalIngestTransientError` —
  the in-sandbox append script (mirrors ``IndexRunError`` / ``IndexRunTransientError``).

Reused as-is: :class:`IndexingConfigError`, :class:`IndexSandboxCreateError`,
:class:`IndexGitCloneError` / :class:`IndexGitCloneTransientError`,
:class:`ScriptSetupError`, :class:`IndexingError`, :class:`TransientIndexingError`.
"""

from __future__ import annotations

from app.services.indexing.errors import IndexingError, TransientIndexingError

__all__ = [
    "DeleteChunksError",
    "DeleteChunksTransientError",
    "IncrementalIngestError",
    "IncrementalIngestTransientError",
]


class DeleteChunksError(IndexingError):
    """The host-side LanceDB delete failed finally. Not retried.

    Covers the "repo is marked indexed but the dataset / table is
    missing" inconsistency — a transient S3 blip cannot fix that, and
    retrying would just burn attempts.
    """

    def __init__(self, message: str | None = None, *, cause: str = "") -> None:
        self.cause = cause
        super().__init__(message or f"delete stale chunks failed: {cause}")


class DeleteChunksTransientError(TransientIndexingError):
    """LanceDB / S3 transport hiccup during the delete. DBOS retries."""

    def __init__(self, message: str | None = None, *, cause: str = "") -> None:
        self.cause = cause
        super().__init__(message or f"delete stale chunks transient failure: {cause}")


class IncrementalIngestError(IndexingError):
    """The in-sandbox incremental append script exited non-zero. Final.

    Note: ``exit_code == -1`` is routed to
    :class:`IncrementalIngestTransientError` (sandbox runner dropout)
    instead, mirroring the full-index ``IndexRunError`` mapping.
    """

    def __init__(
        self,
        message: str | None = None,
        *,
        exit_code: int = 0,
        output_tail: str = "",
    ) -> None:
        self.exit_code = exit_code
        self.output_tail = output_tail
        super().__init__(
            message
            or f"in-sandbox incremental index failed (exit_code={exit_code}): {output_tail}"
        )


class IncrementalIngestTransientError(TransientIndexingError):
    """The sandbox runner dropped mid incremental ingest. DBOS retries."""

    def __init__(self, message: str | None = None, *, cause: str = "") -> None:
        self.cause = cause
        super().__init__(
            message or f"in-sandbox incremental ingest transient failure: {cause}"
        )
