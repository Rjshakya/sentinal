### packages/api/src/app/services/agent/setup_workflow/steps/__init__.py

```diff

new file mode 100644
index 0000000..16cdf30
--- /dev/null
+++ b/packages/api/src/app/services/agent/setup_workflow/steps/__init__.py
@@ -0,0 +1,28 @@
          2 +"""Setup pipeline steps.
          3 +
          4 +One module per I/O boundary. Each step is a :func:`@DBOS.step` (or
          5 +:func:`@dbos_datasource.transaction` for DB-only work) called by
          6 +:func:`app.services.agent.setup_workflow.workflow.setup_workflow`.
          7 +
          8 +The split mirrors the review pipeline's
          9 +:mod:`app.services.review.steps` package: one file, one concern, no
         10 +cross-imports between siblings.
         11 +"""
         12 +
         13 +from __future__ import annotations
         14 +
         15 +from app.services.agent.setup_workflow.steps.ensure_repo_and_sandbox import (
         16 +    ensure_repo_and_sandbox_step,
         17 +)
         18 +from app.services.agent.setup_workflow.steps.git_clone import git_clone_step
         19 +from app.services.agent.setup_workflow.steps.mint_installation_token import (
         20 +    mint_installation_token_step,
         21 +)
         22 +from app.services.agent.setup_workflow.steps.stop_sandbox import stop_setup_sandbox_step
         23 +
         24 +__all__ = [
         25 +    "ensure_repo_and_sandbox_step",
         26 +    "git_clone_step",
         27 +    "mint_installation_token_step",
         28 +    "stop_setup_sandbox_step",
         29 +]

```
