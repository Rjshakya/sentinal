### packages/api/src/app/services/setup/workflow.py

```diff

index e778c14..439050a 100644
--- a/packages/api/src/app/services/setup/workflow.py
+++ b/packages/api/src/app/services/setup/workflow.py
@@ -25,6 +25,7 @@ Sandbox lifecycle: created in the first step, paused in the
   26    26  from __future__ import annotations
   27    27  
   28    28  import logging
         29 +from typing import Optional
   29    30  
   30    31  from dbos import DBOS, SetWorkflowID
   31    32  
@@ -68,7 +69,7 @@ async def setup_workflow(input: SetupWorkflowInput) -> SetupWorkflowResult:
   69    70      mirror steps in :mod:`app.services.indexing.steps.update_repo`;
   70    71      the user can always click "Index" manually to retry.
   71    72      """
   72       -    ctx: RepoContext | None = None
         73 +    ctx: Optional[RepoContext] = None
   73    74      try:
   74    75          ctx = await ensure_repo_and_sandbox_step(input)
   75    76  
@@ -117,7 +118,7 @@ async def _dispatch_indexing(
  118   119      user_id: str,
  119   120      repo_owner: str,
  120   121      repo_name: str,
  121       -    default_branch: str | None,
        122 +    default_branch: Optional[str],
  122   123      local_repo_id: str,
  123   124  ) -> None:
  124   125      """Fire-and-forget dispatch of :func:`indexRepo` for this repo.

```
