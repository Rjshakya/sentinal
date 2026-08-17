"""DBOS durable workflow for the indexing pipeline.

Straight-line sequence of typed :func:`@DBOS.step` calls — the same
shape as :func:`app.services.indexing.workflow.indexRepo`'s setup
counterpart. Each step raises an :class:`IndexingError` subclass on
failure; DBOS retries transient variants and short-circuits on final
ones. The workflow re-raises any caught :class:`IndexingError` so DBOS
records the typed error on the result.

Sandbox lifecycle: created in the first step, killed in ``finally``.
The :class:`IndexContext` carries the durable ``sandbox_id``; every
step reconnects via :meth:`E2BSandbox.connect`.

Lifecycle mirror: alongside the in-memory workflow, four best-effort
state-transition steps in :mod:`app.services.indexing.steps.index_run_steps`
project the workflow's state onto the ``index_runs`` table so the
dashboard can poll progress without depending on DBOS's own
workflow-state table. A failure to update the row never breaks the
workflow itself — the DBOS workflow state is the source of truth for
execution.

Repo mirror: the terminal ``SUCCESS`` / ``ERROR`` paths also call
:func:`mark_repo_indexed_success_step` / :func:`mark_repo_indexed_error_step`
from :mod:`app.services.indexing.steps.update_repo` to flip the
parent :class:`app.models.repo.Repo` row's ``is_indexed`` flag and
populate ``indexed_run_id``. These let the repo list endpoint and
dashboard show ``is_indexed = true | false`` without scanning
``index_runs``.

Idempotency: dispatch with the deterministic id
:func:`app.services.indexing.helpers.index_workflow_id` —
``index:{owner}:{repo}`` — so duplicate dispatches dedupe and the
in-sandbox ``mode="overwrite"`` write is a safe full rewrite.
"""

from __future__ import annotations

import logging

from dbos import DBOS

from app.core.config import settings
from app.services.indexing.errors import IndexingError, NoChunksError
from app.services.indexing.steps import (
    create_index_run_step,
    ensureIndexSandbox,
    getRepoUrl,
    gitCloneToSandbox,
    mark_index_run_error_step,
    mark_index_run_running_step,
    mark_index_run_success_step,
    mark_repo_indexed_error_step,
    mark_repo_indexed_success_step,
    runIndexPipeline,
    stopIndexerSandbox,
    uploadScriptsToSandbox,
)
from app.services.indexing.types import (
    IndexContext,
    IndexRunResult,
    IndexWorkflowInput,
)

log = logging.getLogger(__name__)


@DBOS.workflow()
async def indexRepo(input: IndexWorkflowInput) -> IndexRunResult:
    """Durable workflow: index one arbitrary repo end-to-end.

    Sequence:

    1. **STARTING** — :func:`create_index_run_step` inserts a
       ``STARTING`` row in ``index_runs`` (best-effort; ``None`` on
       failure).
    2. **RUNNING** — sandbox is created; the row flips to ``RUNNING``
       and :attr:`IndexRun.sandbox_id` is populated (best-effort).
    3. :func:`getRepoUrl` — resolve the authenticated clone URL from
       the repo's installation (installation lookup + token mint;
       private-repo support).
    4. clone → upload scripts → combined chunking + ingestion.
    5. **SUCCESS** — ``index_runs`` row flips to ``SUCCESS`` with
       chunk + file counts (best-effort); the parent
       :class:`app.models.repo.Repo` row flips to
       ``is_indexed = true`` with ``indexed_run_id`` back-pointed to
       this :class:`IndexRun` (best-effort).
    6. **ERROR** — typed :class:`IndexingError` is caught;
       ``index_runs`` row flips to ``ERROR`` with the class name +
       message (best-effort); the parent :class:`Repo` row flips to
       ``is_indexed = false`` with ``indexed_run_id`` back-pointed to
       the failed run (best-effort).

    The sandbox is killed in ``finally`` regardless of the outcome.
    """
    ctx: IndexContext | None = None
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

        ctx = await ensureIndexSandbox(input)

        await mark_index_run_running_step(
            run_id=run_id,
            sandbox_id=ctx.sandbox_id,
        )

        # Private-repo support: resolve an authenticated clone URL
        # (installation lookup + token mint). Fails hard with a typed
        # error when the repo's installation row is missing.
        clone_url = await getRepoUrl(
            user_id=input.user_id,
            repo_owner=ctx.repo_owner,
            repo_name=ctx.repo_name,
        )

        await gitCloneToSandbox(ctx=ctx, clone_url=clone_url)
        await uploadScriptsToSandbox(ctx=ctx)

        chunk_count, file_count = await runIndexPipeline(ctx=ctx)
        if chunk_count == 0:
            raise NoChunksError(
                repo_owner=ctx.repo_owner,
                repo_name=ctx.repo_name,
            )

        await mark_index_run_success_step(
            run_id=run_id,
            chunk_count=chunk_count,
            file_count=file_count,
        )

        # Repo mirror: mark the parent Repo row as successfully indexed
        # so the /github/repos endpoint (and the dashboard's
        # ``is_indexed`` flag) reflects the latest run without needing
        # to scan ``index_runs``.
        await mark_repo_indexed_success_step(
            repo_id=input.local_repo_id,
            run_id=run_id,
        )

        return IndexRunResult(
            repo_owner=ctx.repo_owner,
            repo_name=ctx.repo_name,
            chunk_count=chunk_count,
            file_count=file_count,
        )

    except IndexingError as exc:
        log.warning(
            "index_workflow: caught %s repo_url=%s: %s",
            type(exc).__name__,
            input.repo_url,
            exc,
        )
        await mark_index_run_error_step(
            run_id=run_id,
            error_name=type(exc).__name__,
            error_message=str(exc),
        )
        # Repo mirror: keep ``indexed_run_id`` back-pointed to the
        # last failed run (useful for the dashboard's debugging
        # surface area) while flipping ``is_indexed`` back to False.
        await mark_repo_indexed_error_step(
            repo_id=input.local_repo_id,
            run_id=run_id,
        )
        raise
    finally:
        if ctx is not None:
            await stopIndexerSandbox(ctx=ctx)


__all__ = [
    "IndexRunResult",
    "IndexWorkflowInput",
    "indexRepo",
]
