### packages/api/src/app/routers/ai.py

```diff

index fd564f8..9f0be02 100644
--- a/packages/api/src/app/routers/ai.py
+++ b/packages/api/src/app/routers/ai.py
@@ -13,7 +13,7 @@ Two routes:
   14    14    no row is persisted beyond DBOS's own workflow state.
   15    15  
   16    16  The router is a thin shell. All setup logic lives in
   17       -:mod:`app.services.setup.workflow` and its step modules; the
         17 +:mod:`app.services.agent.setup_workflow.workflow` and its step modules; the
   18    18  router only handles request validation, the Repo-row skip check,
   19    19  and the DBOS dispatch / status read.
   20    20  """
@@ -36,8 +36,8 @@ from app.schemas.setup import (
   37    37      SetupWorkflowHandle,
   38    38      StartSetupResponse,
   39    39  )
   40       -from app.services.setup.types import SetupWorkflowInput
   41       -from app.services.setup.workflow import setup_workflow
         40 +from app.services.agent.setup_workflow.types import SetupWorkflowInput
         41 +from app.services.agent.setup_workflow.workflow import setup_workflow
   42    42  
   43    43  log = logging.getLogger(__name__)
   44    44  
@@ -150,7 +150,6 @@ async def start_setup_repos(
  151   151              installation_id=r.installation_id,
  152   152              llm_config=settings.llm_config,
  153   153              default_branch=r.default_branch,
  154       -            index_after_setup=settings.indexing_configured,
  155   154          )
  156   155  
  157   156          workflow_info = await DBOS.start_workflow_async(setup_workflow, workflow_input)

```
