### packages/api/src/app/services/indexing/incremental/errors.py

```diff

deleted file mode 100644
index d44c426..0000000
--- a/packages/api/src/app/services/indexing/incremental/errors.py
+++ /dev/null
@@ -1,87 +0,0 @@
    2       -"""Typed step errors for the incremental indexing pipeline.
    3       -
    4       -Reuses the full-index hierarchy from
    5       -:mod:`app.services.indexing.errors` (the marker base
    6       -:class:`TransientIndexingError` + the ``_should_retry_index``
    7       -predicate) so every ``@DBOS.step`` in this pipeline applies the same
    8       -retry policy:
    9       -
   10       -    should_retry=_should_retry_index
   11       -
   12       -New variants only where the incremental path adds failure modes that
   13       -the full index cannot hit:
   14       -
   15       -- :class:`DeleteChunksError` / :class:`DeleteChunksTransientError` —
   16       -  the host-side LanceDB delete step.
   17       -- :class:`IncrementalIngestError` / :class:`IncrementalIngestTransientError` —
   18       -  the in-sandbox append script (mirrors ``IndexRunError`` / ``IndexRunTransientError``).
   19       -
   20       -Reused as-is: :class:`IndexingConfigError`, :class:`IndexSandboxCreateError`,
   21       -:class:`IndexGitCloneError` / :class:`IndexGitCloneTransientError`,
   22       -:class:`ScriptSetupError`, :class:`IndexingError`, :class:`TransientIndexingError`.
   23       -"""
   24       -
   25       -from __future__ import annotations
   26       -
   27       -from app.services.indexing.errors import IndexingError, TransientIndexingError
   28       -
   29       -__all__ = [
   30       -    "DeleteChunksError",
   31       -    "DeleteChunksTransientError",
   32       -    "IncrementalIngestError",
   33       -    "IncrementalIngestTransientError",
   34       -]
   35       -
   36       -
   37       -class DeleteChunksError(IndexingError):
   38       -    """The host-side LanceDB delete failed finally. Not retried.
   39       -
   40       -    Covers the "repo is marked indexed but the dataset / table is
   41       -    missing" inconsistency — a transient S3 blip cannot fix that, and
   42       -    retrying would just burn attempts.
   43       -    """
   44       -
   45       -    def __init__(self, message: str | None = None, *, cause: str = "") -> None:
   46       -        self.cause = cause
   47       -        super().__init__(message or f"delete stale chunks failed: {cause}")
   48       -
   49       -
   50       -class DeleteChunksTransientError(TransientIndexingError):
   51       -    """LanceDB / S3 transport hiccup during the delete. DBOS retries."""
   52       -
   53       -    def __init__(self, message: str | None = None, *, cause: str = "") -> None:
   54       -        self.cause = cause
   55       -        super().__init__(message or f"delete stale chunks transient failure: {cause}")
   56       -
   57       -
   58       -class IncrementalIngestError(IndexingError):
   59       -    """The in-sandbox incremental append script exited non-zero. Final.
   60       -
   61       -    Note: ``exit_code == -1`` is routed to
   62       -    :class:`IncrementalIngestTransientError` (sandbox runner dropout)
   63       -    instead, mirroring the full-index ``IndexRunError`` mapping.
   64       -    """
   65       -
   66       -    def __init__(
   67       -        self,
   68       -        message: str | None = None,
   69       -        *,
   70       -        exit_code: int = 0,
   71       -        output_tail: str = "",
   72       -    ) -> None:
   73       -        self.exit_code = exit_code
   74       -        self.output_tail = output_tail
   75       -        super().__init__(
   76       -            message
   77       -            or f"in-sandbox incremental index failed (exit_code={exit_code}): {output_tail}"
   78       -        )
   79       -
   80       -
   81       -class IncrementalIngestTransientError(TransientIndexingError):
   82       -    """The sandbox runner dropped mid incremental ingest. DBOS retries."""
   83       -
   84       -    def __init__(self, message: str | None = None, *, cause: str = "") -> None:
   85       -        self.cause = cause
   86       -        super().__init__(
   87       -            message or f"in-sandbox incremental ingest transient failure: {cause}"
   88       -        )

```
