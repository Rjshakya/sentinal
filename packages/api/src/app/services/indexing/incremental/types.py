"""Shared Pydantic types for the incremental indexing pipeline.

Same convention as :mod:`app.services.indexing.types`: every model
here is frozen so DBOS can serialize it across workflow checkpoints,
and the module is circular-import-free so both the workflow and the
pure helpers can import from it.

``IncrementalIndexContext`` subclasses :class:`IndexContext` so every
shared index step (:func:`connect_index_sandbox`,
:func:`gitCloneToSandbox`, :func:`stopIndexerSandbox`) accepts it
directly — the incremental run only adds ``index_files`` on top of
the full-index context shape.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.services.indexing.types import IndexContext

__all__ = [
    "IncrementalIndexContext",
    "IncrementalIndexRunResult",
    "IncrementalIndexWorkflowInput",
    "PushFileSet",
]


class PushFileSet(BaseModel):
    """Typed, deduped view of a GitHub ``push`` payload's changed files.

    Aggregated across **every** commit in the push (``payload["commits"]``),
    not just ``head_commit`` — a multi-commit push only carries the last
    commit's file lists on ``head_commit``.
    """

    model_config = ConfigDict(frozen=True)

    head_sha: str = Field(
        description="Head commit SHA of the pushed ref (full 40-char SHA).",
    )
    added: list[str] = Field(
        default_factory=list,
        description="Repo-root-relative paths of added files (sorted, deduped).",
    )
    removed: list[str] = Field(
        default_factory=list,
        description="Repo-root-relative paths of deleted files (sorted, deduped).",
    )
    modified: list[str] = Field(
        default_factory=list,
        description="Repo-root-relative paths of modified files (sorted, deduped).",
    )


class IncrementalIndexWorkflowInput(BaseModel):
    """Everything the incremental workflow needs to reconcile one push.

    ``files_to_delete`` is ``removed + modified`` (their chunks are
    stale or gone); ``files_to_index`` is ``added + modified`` (their
    current content must be chunked into the dataset). Both may be
    empty; when both are, the workflow is a no-op.

    The canonical identifiers (``repo_owner`` / ``repo_name``) are
    resolved from the push payload by :mod:`app.services.indexing.incremental.webhook`
    and read directly by the workflow — never re-parsed off ``repo_url``
    (same convention as :class:`IndexWorkflowInput`).
    """

    model_config = ConfigDict(frozen=True)

    user_id: str
    repo_owner: str
    repo_name: str
    repo_url: str = Field(
        description="Cloneable repo URL from the push payload's repository object.",
    )
    default_branch: str | None = Field(
        default=None,
        description="The repo's default branch (pinned the sandbox clone).",
    )
    local_repo_id: str = Field(
        description=(
            "Local Repo.id (UUID), resolved by the webhook adapter before "
            "dispatch. Used by the terminal mirror step "
            "(:func:`mark_repo_indexed_success_step`) to keep "
            "``is_indexed`` / ``indexed_run_id`` in sync."
        ),
    )
    head_sha: str = Field(
        description="Head commit SHA; also encodes the deterministic workflow id.",
    )
    files_to_delete: list[str] = Field(
        default_factory=list,
        description="Repo-root-relative paths whose chunks must be dropped (removed + modified).",
    )
    files_to_index: list[str] = Field(
        default_factory=list,
        description="Repo-root-relative paths whose current content must be chunked (added + modified).",
    )


class IncrementalIndexContext(IndexContext):
    """Durable handle for incremental index steps.

    Extends :class:`IndexContext` with the ``index_files`` list the
    in-sandbox append script consumes. Everything else (sandbox id,
    repo identity, paths, table URI) is inherited so the shared index
    steps accept it unchanged.
    """

    files_to_index: list[str] = Field(
        default_factory=list,
        description="Repo-root-relative paths to chunk in the sandbox (added + modified).",
    )


class IncrementalIndexRunResult(BaseModel):
    """The incremental workflow's return value.

    ``error_name`` / ``error_message`` mirror the typed error that
    aborted the workflow, when any. ``deleted_files`` is the number of
    LanceDB rows dropped by the host-side delete step.
    """

    model_config = ConfigDict(frozen=True)

    repo_owner: str
    repo_name: str
    head_sha: str
    deleted_files: int
    chunk_count: int
    file_count: int
    error_name: str | None = None
    error_message: str | None = None
