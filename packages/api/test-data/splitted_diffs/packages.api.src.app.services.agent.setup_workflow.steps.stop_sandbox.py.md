### packages/api/src/app/services/agent/setup_workflow/steps/stop_sandbox.py

```diff

new file mode 100644
index 0000000..ff687d2
--- /dev/null
+++ b/packages/api/src/app/services/agent/setup_workflow/steps/stop_sandbox.py
@@ -0,0 +1,65 @@
          2 +"""Step 6 (in ``finally``): best-effort pause of the E2B sandbox.
          3 +
          4 +The workflow calls this regardless of the outcome of the prior
          5 +steps so a process crash mid-step does not leave the sandbox
          6 +running. Failures here are logged and swallowed: stopping is
          7 +idempotent on the E2B side, and a failed stop would only delay
          8 +(not prevent) cleanup.
          9 +"""
         10 +
         11 +from __future__ import annotations
         12 +
         13 +import logging
         14 +from typing import cast
         15 +
         16 +from dbos import DBOS
         17 +
         18 +from app.core.sandbox.e2b import E2BSandbox, E2BSandboxSpec
         19 +from app.core.sandbox.factory import build_default_spec
         20 +
         21 +log = logging.getLogger(__name__)
         22 +
         23 +
         24 +@DBOS.step()
         25 +async def stop_setup_sandbox_step(
         26 +    *,
         27 +    sandbox_id: str,
         28 +    sandbox_name: str,
         29 +    repo_id: str,
         30 +    user_id: str,
         31 +) -> None:
         32 +    """Pause the E2B sandbox and mark the row ``STOPPED``.
         33 +
         34 +    Best-effort: any exception is logged and swallowed. The
         35 +    :class:`Sandbox` row is updated only if the E2B pause succeeds
         36 +    AND the row exists — a missing row is a no-op so the step is
         37 +    safe to run on a partially-failed workflow.
         38 +
         39 +    Named with the ``setup_`` infix to avoid clashing with the
         40 +    review pipeline's identically-named
         41 +    :func:`app.services.review.steps.stop_sandbox_step` (DBOS
         42 +    registers steps by name, not by module).
         43 +    """
         44 +    spec: E2BSandboxSpec = cast(E2BSandboxSpec, build_default_spec("e2b"))
         45 +
         46 +    try:
         47 +        sandbox = await E2BSandbox.connect(
         48 +            sandbox_id=sandbox_id,
         49 +            sandbox_name=sandbox_name,
         50 +            repo_id=repo_id,
         51 +            user_id=user_id,
         52 +            spec=spec,
         53 +            timeout=60 * 2,
         54 +            api_key=spec.api_key,
         55 +        )
         56 +        await sandbox.stop()
         57 +    except Exception:
         58 +        log.exception(
         59 +            "stop_setup_sandbox_step: pause failed: sandbox_id=%s repo_id=%s",
         60 +            sandbox_id,
         61 +            repo_id,
         62 +        )
         63 +        raise
         64 +
         65 +
         66 +__all__ = ["stop_setup_sandbox_step"]

```
