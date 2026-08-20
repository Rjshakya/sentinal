### packages/api/src/app/services/agent/setup_workflow/workflow.py

```diff

new file mode 100644
index 0000000..2f10145
--- /dev/null
+++ b/packages/api/src/app/services/agent/setup_workflow/workflow.py
@@ -0,0 +1,104 @@
          2 +"""DBOS durable workflow for the per-repo setup pipeline.
          3 +
          4 +The workflow is a straight-line sequence of typed
          5 +:func:`@DBOS.step` calls. Each step raises a :class:`SetupError`
          6 +subclass on failure; DBOS retries when the raised exception is a
          7 +:class:`TransientSetupError` and short-circuits when it is a plain
          8 +:class:`SetupError`. The workflow re-raises any caught
          9 +:class:`SetupError` so DBOS records the typed error name + message on
         10 +the workflow result, which the router surfaces through
         11 +:class:`SetupWorkflowResult`.
         12 +
         13 +Idempotency: the workflow id is
         14 +``f"setup:{user_id}:{github_repo_id}"``. A second ``POST /ai/repo/setup``
         15 +for the same repo reuses the existing workflow if it is still
         16 +running, and returns the cached result if it has already completed.
         17 +The router decides what to do for a workflow in ``ERROR`` state — it
         18 +starts a fresh one (see :mod:`app.routers.ai`).
         19 +
         20 +Sandbox lifecycle: created in the first step, paused in the
         21 +``finally`` block. The :class:`RepoContext` carries the durable
         22 +``sandbox_id`` between steps; each step reconnects via
         23 +:meth:`E2BSandbox.connect`.
         24 +"""
         25 +
         26 +from __future__ import annotations
         27 +
         28 +import logging
         29 +from typing import Optional
         30 +
         31 +from dbos import DBOS
         32 +
         33 +from app.services.agent.setup_workflow.errors import SetupError
         34 +from app.services.agent.setup_workflow.steps import (
         35 +    ensure_repo_and_sandbox_step,
         36 +    git_clone_step,
         37 +    mint_installation_token_step,
         38 +    stop_setup_sandbox_step,
         39 +)
         40 +from app.services.agent.setup_workflow.types import (
         41 +    RepoContext,
         42 +    SetupWorkflowInput,
         43 +    SetupWorkflowResult,
         44 +)
         45 +
         46 +log = logging.getLogger(__name__)
         47 +
         48 +
         49 +# --------------------------------------------------------------------------- #
         50 +# Workflow                                                                     #
         51 +# --------------------------------------------------------------------------- #
         52 +
         53 +
         54 +@DBOS.workflow()
         55 +async def setup_workflow(input: SetupWorkflowInput) -> SetupWorkflowResult:
         56 +    """Durable workflow: configure one repo end-to-end.
         57 +
         58 +    Sequence: ensure repo + sandbox → mint token → git clone.
         59 +    ``stop_setup_sandbox_step`` runs in ``finally`` so the sandbox
         60 +    is paused (not killed) regardless of the outcome. Any typed
         61 +    :class:`SetupError` re-raises so DBOS records the error on the
         62 +    workflow result; the router surfaces it through
         63 +    :class:`SetupWorkflowResult`.
         64 +    """
         65 +    ctx: Optional[RepoContext] = None
         66 +    try:
         67 +        ctx = await ensure_repo_and_sandbox_step(input)
         68 +
         69 +        token = await mint_installation_token_step(
         70 +            github_installation_id=ctx.github_installation_id,
         71 +        )
         72 +
         73 +        await git_clone_step(
         74 +            ctx=ctx,
         75 +            install_token=token,
         76 +        )
         77 +
         78 +        return SetupWorkflowResult(github_repo_id=ctx.github_installation_id)
         79 +
         80 +    except SetupError as exc:
         81 +        log.warning(
         82 +            "setup_workflow: caught %s for user_id=%s repo_id=%s: %s",
         83 +            type(exc).__name__,
         84 +            input.user_id,
         85 +            input.github_repo_id,
         86 +            exc,
         87 +        )
         88 +
         89 +        raise
         90 +    finally:
         91 +        if ctx is not None:
         92 +            await stop_setup_sandbox_step(
         93 +                sandbox_id=ctx.sandbox_id,
         94 +                sandbox_name=ctx.sandbox_name,
         95 +                repo_id=ctx.repo_id,
         96 +                user_id=ctx.user_id,
         97 +            )
         98 +
         99 +
        100 +__all__ = [
        101 +    "RepoContext",
        102 +    "SetupWorkflowInput",
        103 +    "SetupWorkflowResult",
        104 +    "setup_workflow",
        105 +]

```
