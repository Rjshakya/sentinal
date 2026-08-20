### packages/api/src/app/services/indexing/incremental/types.py

```diff

deleted file mode 100644
index 2ac34d1..0000000
--- a/packages/api/src/app/services/indexing/incremental/types.py
+++ /dev/null
@@ -1,135 +0,0 @@
    2       -"""Shared Pydantic types for the incremental indexing pipeline.
    3       -
    4       -Same convention as :mod:`app.services.indexing.types`: every model
    5       -here is frozen so DBOS can serialize it across workflow checkpoints,
    6       -and the module is circular-import-free so both the workflow and the
    7       -pure helpers can import from it.
    8       -
    9       -``IncrementalIndexContext`` subclasses :class:`IndexContext` so every
   10       -shared index step (:func:`connect_index_sandbox`,
   11       -:func:`gitCloneToSandbox`, :func:`stopIndexerSandbox`) accepts it
   12       -directly — the incremental run only adds ``index_files`` on top of
   13       -the full-index context shape.
   14       -"""
   15       -
   16       -from __future__ import annotations
   17       -
   18       -from pydantic import BaseModel, ConfigDict, Field
   19       -
   20       -from app.services.indexing.types import IndexContext
   21       -
   22       -__all__ = [
   23       -    "IncrementalIndexContext",
   24       -    "IncrementalIndexRunResult",
   25       -    "IncrementalIndexWorkflowInput",
   26       -    "PushFileSet",
   27       -]
   28       -
   29       -
   30       -class PushFileSet(BaseModel):
   31       -    """Typed, deduped view of a GitHub ``push`` payload's changed files.
   32       -
   33       -    Aggregated across **every** commit in the push (``payload["commits"]``),
   34       -    not just ``head_commit`` — a multi-commit push only carries the last
   35       -    commit's file lists on ``head_commit``.
   36       -    """
   37       -
   38       -    model_config = ConfigDict(frozen=True)
   39       -
   40       -    head_sha: str = Field(
   41       -        description="Head commit SHA of the pushed ref (full 40-char SHA).",
   42       -    )
   43       -    added: list[str] = Field(
   44       -        default_factory=list,
   45       -        description="Repo-root-relative paths of added files (sorted, deduped).",
   46       -    )
   47       -    removed: list[str] = Field(
   48       -        default_factory=list,
   49       -        description="Repo-root-relative paths of deleted files (sorted, deduped).",
   50       -    )
   51       -    modified: list[str] = Field(
   52       -        default_factory=list,
   53       -        description="Repo-root-relative paths of modified files (sorted, deduped).",
   54       -    )
   55       -
   56       -
   57       -class IncrementalIndexWorkflowInput(BaseModel):
   58       -    """Everything the incremental workflow needs to reconcile one push.
   59       -
   60       -    ``files_to_delete`` is ``removed + modified`` (their chunks are
   61       -    stale or gone); ``files_to_index`` is ``added + modified`` (their
   62       -    current content must be chunked into the dataset). Both may be
   63       -    empty; when both are, the workflow is a no-op.
   64       -
   65       -    The canonical identifiers (``repo_owner`` / ``repo_name``) are
   66       -    resolved from the push payload by :mod:`app.services.indexing.incremental.webhook`
   67       -    and read directly by the workflow — never re-parsed off ``repo_url``
   68       -    (same convention as :class:`IndexWorkflowInput`).
   69       -    """
   70       -
   71       -    model_config = ConfigDict(frozen=True)
   72       -
   73       -    user_id: str
   74       -    repo_owner: str
   75       -    repo_name: str
   76       -    repo_url: str = Field(
   77       -        description="Cloneable repo URL from the push payload's repository object.",
   78       -    )
   79       -    default_branch: str | None = Field(
   80       -        default=None,
   81       -        description="The repo's default branch (pinned the sandbox clone).",
   82       -    )
   83       -    local_repo_id: str = Field(
   84       -        description=(
   85       -            "Local Repo.id (UUID), resolved by the webhook adapter before "
   86       -            "dispatch. Used by the terminal mirror step "
   87       -            "(:func:`mark_repo_indexed_success_step`) to keep "
   88       -            "``is_indexed`` / ``indexed_run_id`` in sync."
   89       -        ),
   90       -    )
   91       -    head_sha: str = Field(
   92       -        description="Head commit SHA; also encodes the deterministic workflow id.",
   93       -    )
   94       -    files_to_delete: list[str] = Field(
   95       -        default_factory=list,
   96       -        description="Repo-root-relative paths whose chunks must be dropped (removed + modified).",
   97       -    )
   98       -    files_to_index: list[str] = Field(
   99       -        default_factory=list,
  100       -        description="Repo-root-relative paths whose current content must be chunked (added + modified).",
  101       -    )
  102       -
  103       -
  104       -class IncrementalIndexContext(IndexContext):
  105       -    """Durable handle for incremental index steps.
  106       -
  107       -    Extends :class:`IndexContext` with the ``index_files`` list the
  108       -    in-sandbox append script consumes. Everything else (sandbox id,
  109       -    repo identity, paths, table URI) is inherited so the shared index
  110       -    steps accept it unchanged.
  111       -    """
  112       -
  113       -    files_to_index: list[str] = Field(
  114       -        default_factory=list,
  115       -        description="Repo-root-relative paths to chunk in the sandbox (added + modified).",
  116       -    )
  117       -
  118       -
  119       -class IncrementalIndexRunResult(BaseModel):
  120       -    """The incremental workflow's return value.
  121       -
  122       -    ``error_name`` / ``error_message`` mirror the typed error that
  123       -    aborted the workflow, when any. ``deleted_files`` is the number of
  124       -    LanceDB rows dropped by the host-side delete step.
  125       -    """
  126       -
  127       -    model_config = ConfigDict(frozen=True)
  128       -
  129       -    repo_owner: str
  130       -    repo_name: str
  131       -    head_sha: str
  132       -    deleted_files: int
  133       -    chunk_count: int
  134       -    file_count: int
  135       -    error_name: str | None = None
  136       -    error_message: str | None = None

```
