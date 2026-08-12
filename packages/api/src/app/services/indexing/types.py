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

    ``repo_url`` is the only required field: the owner/name pair is
    derived from it by :func:`app.services.indexing.helpers.parse_repo_url`.
    ``default_branch`` pins the clone when known; ``user_id`` scopes
    sandbox metadata.
    """

    model_config = ConfigDict(frozen=True)

    user_id: str
    repo_url: str = Field(
        description="Cloneable repo URL (https / ssh / owner:repo).",
    )
    default_branch: str | None = Field(
        default=None,
        description="Branch to check out; when None the remote default is used.",
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
