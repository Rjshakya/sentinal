### packages/api/src/app/services/indexing/incremental/workflow.py

```diff

deleted file mode 100644
index b857b72..0000000
--- a/packages/api/src/app/services/indexing/incremental/workflow.py
+++ /dev/null
@@ -1,169 +0,0 @@
    2       -"""DBOS durable workflow for the incremental indexing pipeline.
    3       -
    4       -Reconciles a default-branch push against the repo's LanceDB dataset.
    5       -Same structural conventions as :func:`app.services.indexing.workflow.indexRepo`:
    6       -
    7       -- Straight-line sequence of typed :func:`@DBOS.step` calls; each step
    8       -  raises an :class:`IndexingError` subclass; DBOS retries transient
    9       -  variants and short-circuits on final ones.
   10       -- Sandbox lifecycle: created in :func:`ensureIncrementalSandbox`
   11       -  (a **fresh** sandbox per run, only when there are files to append),
   12       -  killed in ``finally``. The :class:`IncrementalIndexContext` carries
   13       -  the durable ``sandbox_id``; every step reconnects via
   14       -  :meth:`E2BSandbox.connect`.
   15       -- Lifecycle mirror: the shared ``index_runs`` steps
   16       -  (:func:`create_index_run_step`, :func:`mark_index_run_*`) record one
   17       -  row per run under the deterministic id
   18       -  :func:`app.services.indexing.incremental.helpers.incremental_workflow_id` —
   19       -  ``index:{owner}:{repo}:{head_sha[:7]}`` — so duplicate deliveries of
   20       -  the same head SHA dedupe while distinct commits get distinct runs.
   21       -- Repo mirror: on **success only**, :func:`mark_repo_indexed_success_step`
   22       -  keeps ``is_indexed`` true and back-points ``indexed_run_id`` to this
   23       -  run. On **error the repo row is deliberately untouched**: the dataset
   24       -  still exists (and the host-side delete may have already run), so
   25       -  flipping ``is_indexed`` to ``False`` would be a lie.
   26       -
   27       -Sequence:
   28       -
   29       -1. **STARTING** — :func:`create_index_run_step` (best-effort).
   30       -2. :func:`deleteStaleChunksStep` — host-side delete of the
   31       -   ``removed + modified`` files' chunks (no sandbox).
   32       -3. **If** there are files to append (``added + modified``):
   33       -   sandbox create → ``RUNNING`` mirror → authenticated clone URL →
   34       -   shallow clone → upload scripts → append-only in-sandbox ingest.
   35       -4. **SUCCESS** — ``index_runs`` row flips to ``SUCCESS`` (best-effort);
   36       -   the parent :class:`Repo` row keeps ``is_indexed = true`` with
   37       -   ``indexed_run_id`` back-pointed to this run (best-effort).
   38       -5. **ERROR** — typed :class:`IndexingError` is caught; ``index_runs``
   39       -   row flips to ``ERROR`` (best-effort); **no** repo-row change.
   40       -"""
   41       -
   42       -from __future__ import annotations
   43       -
   44       -import logging
   45       -
   46       -from dbos import DBOS
   47       -
   48       -from app.core.config import settings
   49       -from app.services.indexing.errors import IndexingError
   50       -from app.services.indexing.incremental.steps import (
   51       -    deleteStaleChunksStep,
   52       -    ensureIncrementalSandbox,
   53       -    runIncrementalIngest,
   54       -    uploadIncrementalScripts,
   55       -)
   56       -from app.services.indexing.incremental.types import (
   57       -    IncrementalIndexContext,
   58       -    IncrementalIndexRunResult,
   59       -    IncrementalIndexWorkflowInput,
   60       -)
   61       -from app.services.indexing.steps import (
   62       -    _resolve_table_uri,
   63       -    create_index_run_step,
   64       -    getRepoUrl,
   65       -    gitCloneToSandbox,
   66       -    mark_index_run_error_step,
   67       -    mark_index_run_running_step,
   68       -    mark_index_run_success_step,
   69       -    mark_repo_indexed_success_step,
   70       -    stopIndexerSandbox,
   71       -)
   72       -
   73       -log = logging.getLogger(__name__)
   74       -
   75       -
   76       -@DBOS.workflow()
   77       -async def incrementalIndexRepo(
   78       -    input: IncrementalIndexWorkflowInput,
   79       -) -> IncrementalIndexRunResult:
   80       -    """Durable workflow: reconcile one push against the LanceDB dataset."""
   81       -    ctx: IncrementalIndexContext | None = None
   82       -    run_id: str | None = None
   83       -
   84       -    try:
   85       -        run_id = await create_index_run_step(
   86       -            user_id=input.user_id,
   87       -            repo_owner=input.repo_owner,
   88       -            repo_name=input.repo_name,
   89       -            repo_url=input.repo_url,
   90       -            default_branch=input.default_branch,
   91       -            s3_bucket=settings.index_s3_bucket or None,
   92       -        )
   93       -
   94       -        deleted_files = await deleteStaleChunksStep(
   95       -            table_uri=_resolve_table_uri(owner=input.repo_owner, repo=input.repo_name),
   96       -            files=input.files_to_delete,
   97       -        )
   98       -
   99       -        if input.files_to_index and len(input.files_to_index) > 0:
  100       -            ctx = await ensureIncrementalSandbox(input)
  101       -
  102       -            await mark_index_run_running_step(
  103       -                run_id=run_id,
  104       -                sandbox_id=ctx.sandbox_id,
  105       -            )
  106       -
  107       -            # Private-repo support: resolve an authenticated clone URL
  108       -            # (installation lookup + token mint).
  109       -            clone_url = await getRepoUrl(
  110       -                user_id=input.user_id,
  111       -                repo_owner=ctx.repo_owner,
  112       -                repo_name=ctx.repo_name,
  113       -            )
  114       -
  115       -            await gitCloneToSandbox(ctx=ctx, clone_url=clone_url)
  116       -            await uploadIncrementalScripts(ctx=ctx)
  117       -
  118       -            chunk_count, file_count = await runIncrementalIngest(ctx=ctx)
  119       -        else:
  120       -            chunk_count, file_count = 0, 0
  121       -
  122       -        await mark_index_run_success_step(
  123       -            run_id=run_id,
  124       -            chunk_count=chunk_count,
  125       -            file_count=file_count,
  126       -        )
  127       -
  128       -        # Repo mirror (success only): keep ``is_indexed`` true and
  129       -        # back-point ``indexed_run_id`` to this run.
  130       -        await mark_repo_indexed_success_step(
  131       -            repo_id=input.local_repo_id,
  132       -            run_id=run_id,
  133       -        )
  134       -
  135       -        return IncrementalIndexRunResult(
  136       -            repo_owner=input.repo_owner,
  137       -            repo_name=input.repo_name,
  138       -            head_sha=input.head_sha,
  139       -            deleted_files=deleted_files,
  140       -            chunk_count=chunk_count,
  141       -            file_count=file_count,
  142       -        )
  143       -
  144       -    except IndexingError as exc:
  145       -        log.warning(
  146       -            "incremental_index_workflow: caught %s owner=%s repo=%s head_sha=%s: %s",
  147       -            type(exc).__name__,
  148       -            input.repo_owner,
  149       -            input.repo_name,
  150       -            input.head_sha,
  151       -            exc,
  152       -        )
  153       -        await mark_index_run_error_step(
  154       -            run_id=run_id,
  155       -            error_name=type(exc).__name__,
  156       -            error_message=str(exc),
  157       -        )
  158       -        # Deliberately NOT calling mark_repo_indexed_error_step — the
  159       -        # dataset still exists; the repo stays searchable.
  160       -        raise
  161       -    finally:
  162       -        if ctx is not None:
  163       -            await stopIndexerSandbox(ctx=ctx)
  164       -
  165       -
  166       -__all__ = [
  167       -    "IncrementalIndexRunResult",
  168       -    "IncrementalIndexWorkflowInput",
  169       -    "incrementalIndexRepo",
  170       -]

```
