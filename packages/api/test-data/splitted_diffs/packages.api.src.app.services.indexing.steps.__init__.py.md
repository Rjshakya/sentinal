### packages/api/src/app/services/indexing/steps/__init__.py

```diff

index fd96483..6ee27cf 100644
--- a/packages/api/src/app/services/indexing/steps/__init__.py
+++ b/packages/api/src/app/services/indexing/steps/__init__.py
@@ -3,12 +3,10 @@
    4     4  The pipeline has four steps:
    5     5  
    6     6  1. :func:`ensureIndexSandbox` -- create the E2B sandbox.
    7       -2. :func:`getRepoUrl` -- resolve the authenticated clone URL from
    8       -   the repo's installation (private-repo support).
    9       -3. :func:`gitCloneToSandbox` -- shallow-clone the repo.
   10       -4. :func:`uploadScriptsToSandbox` -- upload ``chunking.py`` +
          7 +2. :func:`gitCloneToSandbox` -- shallow-clone the repo.
          8 +3. :func:`uploadScriptsToSandbox` -- upload ``chunking.py`` +
   11     9     ``ingestion.py``.
   12       -5. :func:`runIndexPipeline` -- combined chunking + ingestion in one
         10 +4. :func:`runIndexPipeline` -- combined chunking + ingestion in one
   13    11     in-sandbox command.
   14    12  
   15    13  Plus a best-effort teardown at the end of the workflow:
@@ -39,7 +37,6 @@ from app.services.indexing.steps.ensure_index_sandbox import (
   40    38      _resolve_table_uri,
   41    39      ensureIndexSandbox,
   42    40  )
   43       -from app.services.indexing.steps.get_repo_url import getRepoUrl
   44    41  from app.services.indexing.steps.git_clone import (
   45    42      build_clone_command,
   46    43      check_git_clone,
@@ -78,7 +75,6 @@ __all__ = [
   79    76      "check_index_run_result",
   80    77      "create_index_run_step",
   81    78      "ensureIndexSandbox",
   82       -    "getRepoUrl",
   83    79      "gitCloneToSandbox",
   84    80      "mark_index_run_error_step",
   85    81      "mark_index_run_running_step",

```
