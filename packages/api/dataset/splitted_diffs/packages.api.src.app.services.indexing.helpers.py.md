### packages/api/src/app/services/indexing/helpers.py

```diff

index 73a76b2..ade0e9e 100644
--- a/packages/api/src/app/services/indexing/helpers.py
+++ b/packages/api/src/app/services/indexing/helpers.py
@@ -2,7 +2,7 @@
    3     3  
    4     4  No I/O, no session, no clock, no settings reads — every function here
    5     5  is testable with ``assert f(x) == y``. Derived from
    6       -:mod:`app.services.setup._helpers`, which establishes
          6 +:mod:`app.services.agent.setup_workflow._helpers`, which establishes
    7     7  this convention for the setup pipeline.
    8     8  """
    9     9  

```
