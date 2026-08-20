### packages/api/src/app/services/agent/setup_workflow/__init__.py

```diff

new file mode 100644
index 0000000..b6740ef
--- /dev/null
+++ b/packages/api/src/app/services/agent/setup_workflow/__init__.py
@@ -0,0 +1,56 @@
          2 +"""Setup pipeline as a DBOS durable workflow.
          3 +
          4 +This subpackage is the new home of the "configure repo" flow. It
          5 +replaces the old ``app.services.agent.setup_pipeline`` /
          6 +``app.services.agent.setup_errors`` modules — those are left in place
          7 +but are no longer imported by the router. Every public symbol lives
          8 +under one of:
          9 +
         10 +- :mod:`app.services.agent.setup_workflow.errors` — typed exception hierarchy.
         11 +- :mod:`app.services.agent.setup_workflow._helpers` — pure functions.
         12 +- :mod:`app.services.agent.setup_workflow.workflow` — the DBOS workflow.
         13 +- :mod:`app.services.agent.setup_workflow.steps` — the workflow's I/O steps.
         14 +
         15 +Re-exports the workflow's public types so callers do not need to know
         16 +the internal layout.
         17 +"""
         18 +
         19 +from __future__ import annotations
         20 +
         21 +from app.services.agent.setup_workflow.errors import (
         22 +    GitCloneError,
         23 +    GitCloneTransientError,
         24 +    InstallTokenMintError,
         25 +    InstallationNotFoundError,
         26 +    SandboxCreateError,
         27 +    SetupAgentCrashedError,
         28 +    SetupAgentNoStructuredResponseError,
         29 +    SetupAgentRateLimitedError,
         30 +    SetupError,
         31 +    TransientSetupError,
         32 +)
         33 +from app.services.agent.setup_workflow.types import (
         34 +    RepoContext,
         35 +    SetupWorkflowInput,
         36 +    SetupWorkflowResult,
         37 +)
         38 +from app.services.agent.setup_workflow.workflow import setup_workflow
         39 +
         40 +
         41 +__all__ = [
         42 +    "GitCloneError",
         43 +    "GitCloneTransientError",
         44 +    "InstallTokenMintError",
         45 +    "InstallationNotFoundError",
         46 +    "RepoContext",
         47 +    "SandboxCreateError",
         48 +    "SetupAgentCrashedError",
         49 +    "SetupAgentNoStructuredResponseError",
         50 +    "SetupAgentRateLimitedError",
         51 +    "SetupError",
         52 +    "SetupWorkflowInput",
         53 +    "SetupWorkflowResult",
         54 +    "TransientSetupError",
         55 +    "setup_workflow",
         56 +]
         57 +

```
