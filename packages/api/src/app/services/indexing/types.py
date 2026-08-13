"""Shared Pydantic types for the indexing pipeline.

Extracted so the workflow, the step modules, and the pure helpers can
import from a single, circular-import-free module — the same split as
:mod:`app.services.agent.setup_workflow.types`. Every model here is
frozen so DBOS can serialize it across workflow checkpoints.

Note: the in-sandbox chunking script defines its own local
:class:`Chunk` Pydantic model (it has no host imports). The host does
not need a mirror — chunks live and die inside the sandbox.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "IndexContext",
    "IndexRunResult",
    "IndexWorkflowInput",
]


class IndexWorkflowInput(BaseModel):
    """Everything the workflow needs to index one arbitrary repo.

    The client (``POST /indexing/repo``) supplies ``repo_owner`` and
    ``repo_name`` as the canonical identifiers — the workflow and its
    steps read them directly and never re-parse them off
    ``repo_url``. ``repo_url`` stays on the input for the audit row
    in ``index_runs`` and for downstream display;
    ``default_branch`` pins the clone when known; ``user_id`` scopes
    sandbox metadata.

    ``local_repo_id`` is the local :class:`app.models.repo.Repo.id`
    (UUID). Every dispatch site resolves it from the user's already
    installed :class:`Repo` row before starting the workflow; the
    workflow passes it to the terminal mirror steps so the parent
    row's ``is_indexed`` flag and ``indexed_run_id`` back-reference
    stay in sync with the :class:`IndexRun` lifecycle.
    """

    model_config = ConfigDict(frozen=True)

    user_id: str
    repo_owner: str = Field(
        description=(
            "GitHub repo owner (org or user). First-class identifier; "
            "supplied by the client and not re-parsed from ``repo_url``."
        ),
    )
    repo_name: str = Field(
        description=(
            "GitHub repo name. First-class identifier; supplied by the "
            "client and not re-parsed from ``repo_url``."
        ),
    )
    repo_url: str = Field(
        description="Cloneable repo URL (https / ssh / owner:repo).",
    )
    default_branch: str | None = Field(
        default=None,
        description="Branch to check out; when None the remote default is used.",
    )
    local_repo_id: str = Field(
        description=(
            "Local Repo.id (UUID), resolved by every dispatch site "
            "before starting the workflow. Used by the terminal mirror "
            "steps (:func:`mark_repo_indexed_success_step` / "
            ":func:`mark_repo_indexed_error_step`) to flip the parent "
            "row's ``is_indexed`` flag and ``indexed_run_id`` back-reference."
        ),
    )


class IndexContext(BaseModel):
    """Durable handle passed between index steps.

    Carries the sandbox id (steps reconnect on demand — the live E2B
    handle never crosses a workflow boundary), the derived repo
    identity, the in-sandbox paths, the table URI, and the batch size
    the ingestion script will use.
    """

    model_config = ConfigDict(frozen=True)

    user_id: str
    sandbox_id: str
    sandbox_name: str
    repo_owner: str
    repo_name: str
    repo_url: str
    default_branch: str | None
    repo_dir: str
    ingest_script_path: str
    table_uri: str
    batch_size: int = Field(
        default=50,
        ge=1,
        description="Batch size the in-sandbox chunking generator yields at.",
    )


class IndexRunResult(BaseModel):
    """The workflow's return value.

    ``error_name`` / ``error_message`` mirror the typed
    :class:`IndexingError` that aborted the workflow, when any; both
    are ``None`` on success.
    """

    model_config = ConfigDict(frozen=True)

    repo_owner: str
    repo_name: str
    chunk_count: int
    file_count: int
    error_name: str | None = None
    error_message: str | None = None
