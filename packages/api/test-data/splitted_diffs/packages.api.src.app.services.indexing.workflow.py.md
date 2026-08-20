### packages/api/src/app/services/indexing/workflow.py

```diff

index e1bdfbd..4fd044d 100644
--- a/packages/api/src/app/services/indexing/workflow.py
+++ b/packages/api/src/app/services/indexing/workflow.py
@@ -44,7 +44,6 @@ from app.services.indexing.errors import IndexingError, NoChunksError
   45    45  from app.services.indexing.steps import (
   46    46      create_index_run_step,
   47    47      ensureIndexSandbox,
   48       -    getRepoUrl,
   49    48      gitCloneToSandbox,
   50    49      mark_index_run_error_step,
   51    50      mark_index_run_running_step,
@@ -75,16 +74,13 @@ async def indexRepo(input: IndexWorkflowInput) -> IndexRunResult:
   76    75         failure).
   77    76      2. **RUNNING** — sandbox is created; the row flips to ``RUNNING``
   78    77         and :attr:`IndexRun.sandbox_id` is populated (best-effort).
   79       -    3. :func:`getRepoUrl` — resolve the authenticated clone URL from
   80       -       the repo's installation (installation lookup + token mint;
   81       -       private-repo support).
   82       -    4. clone → upload scripts → combined chunking + ingestion.
   83       -    5. **SUCCESS** — ``index_runs`` row flips to ``SUCCESS`` with
         78 +    3. clone → upload scripts → combined chunking + ingestion.
         79 +    4. **SUCCESS** — ``index_runs`` row flips to ``SUCCESS`` with
   84    80         chunk + file counts (best-effort); the parent
   85    81         :class:`app.models.repo.Repo` row flips to
   86    82         ``is_indexed = true`` with ``indexed_run_id`` back-pointed to
   87    83         this :class:`IndexRun` (best-effort).
   88       -    6. **ERROR** — typed :class:`IndexingError` is caught;
         84 +    5. **ERROR** — typed :class:`IndexingError` is caught;
   89    85         ``index_runs`` row flips to ``ERROR`` with the class name +
   90    86         message (best-effort); the parent :class:`Repo` row flips to
   91    87         ``is_indexed = false`` with ``indexed_run_id`` back-pointed to
@@ -112,16 +108,7 @@ async def indexRepo(input: IndexWorkflowInput) -> IndexRunResult:
  113   109              sandbox_id=ctx.sandbox_id,
  114   110          )
  115   111  
  116       -        # Private-repo support: resolve an authenticated clone URL
  117       -        # (installation lookup + token mint). Fails hard with a typed
  118       -        # error when the repo's installation row is missing.
  119       -        clone_url = await getRepoUrl(
  120       -            user_id=input.user_id,
  121       -            repo_owner=ctx.repo_owner,
  122       -            repo_name=ctx.repo_name,
  123       -        )
  124       -
  125       -        await gitCloneToSandbox(ctx=ctx, clone_url=clone_url)
        112 +        await gitCloneToSandbox(ctx=ctx)
  126   113          await uploadScriptsToSandbox(ctx=ctx)
  127   114  
  128   115          chunk_count, file_count = await runIndexPipeline(ctx=ctx)

```
