"""Typed step errors for the indexing pipeline.

Every error raised inside a :func:`@DBOS.step` is a subclass of
:class:`IndexingError`. The marker base :class:`TransientIndexingError`
identifies failures DBOS should retry (sandbox blips, LanceDB / S3
hiccups, OpenAI 429 / 5xx). Everything else is a final business
outcome: a malformed repo URL, a clone that cannot succeed, the
missing-config gate, the in-sandbox runner signaling a hard failure
on a chunking / ingest command.

The retry policy at every ``@DBOS.step`` is::

    should_retry=_should_retry_index

so a step only re-runs when the exception it raises inherits from
:class:`TransientIndexingError`. The hierarchy mirrors
:mod:`app.services.agent.setup_workflow.errors` but is named
independently, per that module's convention.

The single :func:`run_index_step` replaces the legacy
``run_chunking_step`` / ``download_chunks_step`` / ``ingest_step``
chain — failures inside the sandbox map to
:class:`IndexRunError` / :class:`IndexRunTransientError` and a final
:class:`NoChunksError` when the in-sandbox summary line reports zero
chunks.
"""

from __future__ import annotations

__all__ = [
    "IndexGitCloneError",
    "IndexGitCloneTransientError",
    "IndexRunError",
    "IndexRunTransientError",
    "IndexSandboxConnectError",
    "IndexSandboxCreateError",
    "IndexingConfigError",
    "IndexingError",
    "InvalidRepoUrlError",
    "NoChunksError",
    "ScriptSetupError",
    "TransientIndexingError",
    "_should_retry_index",
]


class IndexingError(Exception):
    """Base class for every indexing-pipeline step error.

    Every subclass' ``__init__`` takes a positional ``message`` first
    (defaulting to the formatted description) plus keyword-only
    attributes. DBOS pickles step exceptions and rebuilds them as
    ``cls(*args)`` — a keyword-only signature makes that round-trip
    fail and ``WorkflowStatus.error`` degrade to a string, losing the
    typed error the router surfaces as ``error_name``.
    """


class TransientIndexingError(IndexingError):
    """Marker base for transient failures DBOS should retry.

    Subclasses encode failures expected to clear up on a subsequent
    attempt: sandbox create / connect / IO dropouts, OpenAI / S3
    transport errors. Steps that want DBOS-managed retry set
    ``should_retry=_should_retry_index``.
    """


def _should_retry_index(exc: BaseException) -> bool:
    """DBOS ``should_retry`` predicate: retry only on transient errors."""
    return isinstance(exc, TransientIndexingError)


class InvalidRepoUrlError(IndexingError):
    """The ``repo_url`` could not be parsed into an ``owner/repo`` pair.

    Final — not retried. The URL is a caller-supplied input, not a
    transient condition.
    """

    def __init__(
        self,
        message: str | None = None,
        *,
        repo_url: str = "",
        reason: str = "",
    ) -> None:
        self.repo_url = repo_url
        self.reason = reason
        super().__init__(message or f"invalid repo_url {repo_url!r}: {reason}")


class IndexSandboxCreateError(TransientIndexingError):
    """E2B sandbox creation failed transiently. DBOS retries the step."""

    def __init__(self, message: str | None = None, *, cause: str = "") -> None:
        self.cause = cause
        super().__init__(message or f"sandbox create failed: {cause}")


class IndexSandboxConnectError(TransientIndexingError):
    """Reconnecting to the E2B sandbox by id failed. DBOS retries."""

    def __init__(self, message: str | None = None, *, cause: str = "") -> None:
        self.cause = cause
        super().__init__(message or f"sandbox connect failed: {cause}")


class IndexGitCloneError(IndexingError):
    """``git clone`` inside the sandbox exited non-zero. Final."""

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
            message or f"git clone failed (exit_code={exit_code}): {output_tail}"
        )


class IndexGitCloneTransientError(TransientIndexingError):
    """The sandbox became unavailable mid-clone. DBOS retries."""

    def __init__(self, message: str | None = None, *, cause: str = "") -> None:
        self.cause = cause
        super().__init__(message or f"git clone transient sandbox failure: {cause}")


class ScriptSetupError(TransientIndexingError):
    """Writing the chunking / ingestion scripts into the sandbox failed.

    Filesystem or network blips; both writes are idempotent so DBOS
    can safely retry.
    """

    def __init__(self, message: str | None = None, *, cause: str = "") -> None:
        self.cause = cause
        super().__init__(message or f"script setup failed: {cause}")


class IndexRunError(IndexingError):
    """The combined chunking-and-ingest in-sandbox command exited non-zero.

    Final — once a chunking/ingest script exits non-zero, retrying the
    same input is unlikely to clear the failure (it is a logic bug or
    an unsupported input). Note: ``exit_code == -1`` is treated as a
    sandbox runner dropout and routed to
    :class:`IndexRunTransientError` instead.
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
            message or f"in-sandbox index failed (exit_code={exit_code}): {output_tail}"
        )


class IndexRunTransientError(TransientIndexingError):
    """The sandbox runner dropped mid in-sandbox index command. DBOS retries."""

    def __init__(self, message: str | None = None, *, cause: str = "") -> None:
        self.cause = cause
        super().__init__(message or f"in-sandbox index transient sandbox failure: {cause}")


class NoChunksError(IndexingError):
    """The in-sandbox pipeline reported zero chunks. Final.

    Usually means the repo has no files in a supported language (or
    only files larger than the size cap). Indexing an empty dataset is
    pointless, so the workflow surfaces this as a terminal error.
    """

    def __init__(
        self,
        message: str | None = None,
        *,
        repo_owner: str = "",
        repo_name: str = "",
    ) -> None:
        self.repo_owner = repo_owner
        self.repo_name = repo_name
        super().__init__(
            message
            or f"repo {repo_owner}/{repo_name} produced no chunks "
            "(no supported-language files?)"
        )


class IndexingConfigError(IndexingError):
    """Required indexing configuration is missing. Final.

    Raised by steps that gate on :attr:`app.core.config.Settings.indexing_configured`.
    """

    def __init__(
        self,
        message: str | None = None,
        *,
        detail: str | None = None,
    ) -> None:
        self.detail = detail
        super().__init__(message or detail or "indexing is not configured")
