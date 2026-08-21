"""DBOS durable workflow for the incremental indexing pipeline.

Reconciles a default-branch push against the repo's LanceDB dataset.
Same structural conventions as :func:`app.services.indexing.workflow.indexRepo`:

- Straight-line sequence of typed :func:`@DBOS.step` calls; each step
  raises an :class:`IndexingError` subclass; DBOS retries transient
  variants and short-circuits on final ones.
- Sandbox lifecycle: created in :func:`ensureIncrementalSandbox`
  (a **fresh** sandbox per run, only when there are files to append),
  killed in ``finally``. The :class:`IncrementalIndexContext` carries
  the durable ``sandbox_id``; every step reconnects via
  :meth:`E2BSandbox.connect`.
- Lifecycle mirror: the shared ``index_runs`` steps
  (:func:`create_index_run_step`, :func:`mark_index_run_*`) record one
  row per run under the deterministic id
  :func:`app.services.indexing.incremental.helpers.incremental_workflow_id` —
  ``index:{owner}:{repo}:{head_sha[:7]}`` — so duplicate deliveries of
  the same head SHA dedupe while distinct commits get distinct runs.
- Repo mirror: on **success only**, :func:`mark_repo_indexed_success_step`
  keeps ``is_indexed`` true and back-points ``indexed_run_id`` to this
  run. On **error the repo row is deliberately untouched**: the dataset
  still exists (and the host-side delete may have already run), so
  flipping ``is_indexed`` to ``False`` would be a lie.

Sequence:

1. **STARTING** — :func:`create_index_run_step` (best-effort).
2. :func:`deleteStaleChunksStep` — host-side delete of the
   ``removed + modified`` files' chunks (no sandbox).
3. **If** there are files to append (``added + modified``):
   sandbox create → ``RUNNING`` mirror → authenticated clone URL →
   shallow clone → upload scripts → append-only in-sandbox ingest.
4. **SUCCESS** — ``index_runs`` row flips to ``SUCCESS`` (best-effort);
   the parent :class:`Repo` row keeps ``is_indexed = true`` with
   ``indexed_run_id`` back-pointed to this run (best-effort).
5. **ERROR** — typed :class:`IndexingError` is caught; ``index_runs``
   row flips to ``ERROR`` (best-effort); **no** repo-row change.
"""

from __future__ import annotations

import logging

from dbos import DBOS

from app.core.config import settings
from app.services.indexing.errors import IndexingError
from app.services.indexing.incremental.steps import (
    deleteStaleChunksStep,
    ensureIncrementalSandbox,
    runIncrementalIngest,
    uploadIncrementalScripts,
)
from app.services.indexing.incremental.types import (
    IncrementalIndexContext,
    IncrementalIndexRunResult,
    IncrementalIndexWorkflowInput,
)
from app.services.indexing.steps import (
    _resolve_table_uri,
    create_index_run_step,
    getRepoUrl,
    gitCloneToSandbox,
    mark_index_run_error_step,
    mark_index_run_running_step,
    mark_index_run_success_step,
    mark_repo_indexed_success_step,
    stopIndexerSandbox,
)

log = logging.getLogger(__name__)


@DBOS.workflow()
async def incrementalIndexRepo(
    input: IncrementalIndexWorkflowInput,
) -> IncrementalIndexRunResult:
    """Durable workflow: reconcile one push against the LanceDB dataset."""
    ctx: IncrementalIndexContext | None = None
    run_id: str | None = None

    try:
        run_id = await create_index_run_step(
            user_id=input.user_id,
            repo_owner=input.repo_owner,
            repo_name=input.repo_name,
            repo_url=input.repo_url,
            default_branch=input.default_branch,
            s3_bucket=settings.index_s3_bucket or None,
        )

        deleted_files = await deleteStaleChunksStep(
            table_uri=_resolve_table_uri(owner=input.repo_owner, repo=input.repo_name),
            files=input.files_to_delete,
        )

        if input.files_to_index and len(input.files_to_index) > 0:
            ctx = await ensureIncrementalSandbox(input)

            await mark_index_run_running_step(
                run_id=run_id,
                sandbox_id=ctx.sandbox_id,
            )

            # Private-repo support: resolve an authenticated clone URL
            # (installation lookup + token mint).
            clone_url = await getRepoUrl(
                user_id=input.user_id,
                repo_owner=ctx.repo_owner,
                repo_name=ctx.repo_name,
            )

            await gitCloneToSandbox(ctx=ctx, clone_url=clone_url)
            await uploadIncrementalScripts(ctx=ctx)

            chunk_count, file_count = await runIncrementalIngest(ctx=ctx)
        else:
            chunk_count, file_count = 0, 0

        await mark_index_run_success_step(
            run_id=run_id,
            chunk_count=chunk_count,
            file_count=file_count,
        )

        # Repo mirror (success only): keep ``is_indexed`` true and
        # back-point ``indexed_run_id`` to this run.
        await mark_repo_indexed_success_step(
            repo_id=input.local_repo_id,
            run_id=run_id,
        )

        return IncrementalIndexRunResult(
            repo_owner=input.repo_owner,
            repo_name=input.repo_name,
            head_sha=input.head_sha,
            deleted_files=deleted_files,
            chunk_count=chunk_count,
            file_count=file_count,
        )

    except IndexingError as exc:
        log.warning(
            "incremental_index_workflow: caught %s owner=%s repo=%s head_sha=%s: %s",
            type(exc).__name__,
            input.repo_owner,
            input.repo_name,
            input.head_sha,
            exc,
        )
        await mark_index_run_error_step(
            run_id=run_id,
            error_name=type(exc).__name__,
            error_message=str(exc),
        )
        # Deliberately NOT calling mark_repo_indexed_error_step — the
        # dataset still exists; the repo stays searchable.
        raise
    finally:
        if ctx is not None:
            await stopIndexerSandbox(ctx=ctx)


__all__ = [
    "IncrementalIndexRunResult",
    "IncrementalIndexWorkflowInput",
    "incrementalIndexRepo",
]
