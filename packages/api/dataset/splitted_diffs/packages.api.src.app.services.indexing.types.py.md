### packages/api/src/app/services/indexing/types.py

```diff

index 989f236..e0911d8 100644
--- a/packages/api/src/app/services/indexing/types.py
+++ b/packages/api/src/app/services/indexing/types.py
@@ -2,7 +2,7 @@
    3     3  
    4     4  Extracted so the workflow, the step modules, and the pure helpers can
    5     5  import from a single, circular-import-free module — the same split as
    6       -:mod:`app.services.setup.types`. Every model here is
          6 +:mod:`app.services.agent.setup_workflow.types`. Every model here is
    7     7  frozen so DBOS can serialize it across workflow checkpoints.
    8     8  
    9     9  Note: the in-sandbox chunking script defines its own local

```
