### packages/api/src/app/schemas/setup.py

```diff

index 4476c86..31d848d 100644
--- a/packages/api/src/app/schemas/setup.py
+++ b/packages/api/src/app/schemas/setup.py
@@ -9,7 +9,7 @@ through ``error_name`` / ``error_message`` on
   10    10  workflow's own DBOS-managed state.
   11    11  
   12    12  The schemas here are the HTTP-shape contract only; the workflow
   13       -itself lives in :mod:`app.services.setup.workflow`.
         13 +itself lives in :mod:`app.services.agent.setup_workflow.workflow`.
   14    14  """
   15    15  
   16    16  from __future__ import annotations

```
