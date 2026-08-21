### packages/api/src/app/services/indexing/steps/index_run_steps.py

```diff

index dc451b8..959c3f5 100644
--- a/packages/api/src/app/services/indexing/steps/index_run_steps.py
+++ b/packages/api/src/app/services/indexing/steps/index_run_steps.py
@@ -20,7 +20,7 @@ table is the user-facing mirror that the dashboard polls.
   21    21  The :func:`@DBOS.step` decorator (rather than
   22    22  :func:`@dbos_datasource.transaction`) keeps the steps consistent with
   23    23  the rest of the indexing pipeline — see
   24       -:func:`app.services.setup.steps.ensure_repo_and_sandbox.ensure_repo_and_sandbox_step`
         24 +:func:`app.services.agent.setup_workflow.steps.ensure_repo_and_sandbox.ensure_repo_and_sandbox_step`
   25    25  for the same pattern.
   26    26  """
   27    27  

```
