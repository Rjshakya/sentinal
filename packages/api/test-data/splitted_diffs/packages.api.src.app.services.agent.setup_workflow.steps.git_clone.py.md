### packages/api/src/app/services/agent/setup_workflow/steps/git_clone.py

```diff

new file mode 100644
index 0000000..017f499
--- /dev/null
+++ b/packages/api/src/app/services/agent/setup_workflow/steps/git_clone.py
@@ -0,0 +1,139 @@
          2 +"""Step 3: shallow ``git clone`` of the repo into the E2B sandbox.
          3 +
          4 +Reconnects to the sandbox by id (the in-process handle is gone
          5 +after a workflow resume), creates the workspace folder, runs the
          6 +clone with the authenticated URL, and validates the exit code.
          7 +"""
          8 +
          9 +from __future__ import annotations
         10 +
         11 +import logging
         12 +from typing import cast
         13 +
         14 +from dbos import DBOS
         15 +
         16 +from app.core.sandbox.e2b import E2BSandbox, E2BSandboxSpec
         17 +from app.core.sandbox.factory import build_default_spec
         18 +from app.services.agent.setup_workflow._helpers import (
         19 +    build_authenticated_clone_url,
         20 +    check_git_clone_result,
         21 +)
         22 +from app.services.agent.setup_workflow.types import RepoContext
         23 +from app.utils.util import workspace_path
         24 +
         25 +log = logging.getLogger(__name__)
         26 +
         27 +CLONE_TIMEOUT_S: float = 300.0
         28 +"""Upper bound on the wall-clock duration of a single ``git clone``.
         29 +
         30 +300 s covers most first-time clones of moderate-size public repos.
         31 +Private monorepos that have to negotiate through a slow network
         32 +will hit this; the workflow's step retry policy handles it as a
         33 +:class:`GitCloneTransientError` (sandbox-side runner failure) or a
         34 +:class:`GitCloneError` (real ``git`` failure) depending on the exit
         35 +code path.
         36 +"""
         37 +
         38 +
         39 +def _should_retry_setup(exc: BaseException) -> bool:
         40 +    from app.services.agent.setup_workflow.errors import TransientSetupError
         41 +
         42 +    return isinstance(exc, TransientSetupError)
         43 +
         44 +
         45 +@DBOS.step(
         46 +    retries_allowed=True,
         47 +    max_attempts=2,
         48 +    should_retry=_should_retry_setup,
         49 +)
         50 +async def git_clone_step(
         51 +    *,
         52 +    ctx: RepoContext,
         53 +    install_token: str,
         54 +) -> None:
         55 +    """Shallow-clone ``ctx.repo_owner/ctx.repo_name`` into the sandbox.
         56 +
         57 +    Reconnects to the E2B sandbox via
         58 +    :meth:`E2BSandbox.connect`. The reconnect itself is wrapped —
         59 +    transient connect failures raise
         60 +    :class:`GitCloneTransientError` (retry) while other SDK errors
         61 +    are re-raised as :class:`GitCloneError` (final).
         62 +
         63 +    The :func:`check_git_clone_result` helper maps the
         64 +    ``CommandResult`` to the typed error hierarchy:
         65 +
         66 +    - ``exit_code == 0``  → success
         67 +    - ``exit_code == -1`` → :class:`GitCloneTransientError`
         68 +      (sandbox-side runner failure — DBOS retries)
         69 +    - ``exit_code > 0``   → :class:`GitCloneError` (real git failure)
         70 +
         71 +    Raises:
         72 +        GitCloneTransientError: sandbox-side command runner failure.
         73 +            Retried by DBOS. The clone step reconnects via
         74 +            :meth:`E2BSandbox.connect` and re-runs the command, so a
         75 +            transient disconnect does not require a fresh sandbox.
         76 +        GitCloneError: the ``git clone`` itself failed (non-zero
         77 +            exit code, bad token, missing repo, transport error).
         78 +            Final — not retried.
         79 +    """
         80 +    spec: E2BSandboxSpec = cast(E2BSandboxSpec, build_default_spec("e2b"))
         81 +
         82 +    try:
         83 +        sandbox = await E2BSandbox.connect(
         84 +            sandbox_id=ctx.sandbox_id,
         85 +            sandbox_name=ctx.sandbox_name,
         86 +            repo_id=ctx.repo_id,
         87 +            user_id=ctx.user_id,
         88 +            spec=spec,
         89 +            timeout=60 * 60,
         90 +            api_key=spec.api_key,
         91 +        )
         92 +    except Exception as exc:
         93 +        log.warning(
         94 +            "git_clone: sandbox reconnect failed (will retry): user_id=%s "
         95 +            "repo_id=%s sandbox_id=%s cause=%s: %s",
         96 +            ctx.user_id,
         97 +            ctx.repo_id,
         98 +            ctx.sandbox_id,
         99 +            type(exc).__name__,
        100 +            exc,
        101 +        )
        102 +        # Treat all reconnect failures as transient — DBOS retries.
        103 +        from app.services.agent.setup_workflow.errors import GitCloneTransientError
        104 +
        105 +        raise GitCloneTransientError(
        106 +            cause=f"reconnect failed: {type(exc).__name__}: {exc}"
        107 +        ) from exc
        108 +
        109 +    try:
        110 +        await sandbox.fs_create_folder(workspace_path())
        111 +        clone_url = build_authenticated_clone_url(
        112 +            install_token=install_token,
        113 +            owner=ctx.repo_owner,
        114 +            name=ctx.repo_name,
        115 +        )
        116 +        result = await sandbox.execute(
        117 +            f"git clone {clone_url} {ctx.repo_name}",
        118 +            cwd=workspace_path(),
        119 +            timeout=CLONE_TIMEOUT_S,
        120 +        )
        121 +        check_git_clone_result(result)
        122 +    finally:
        123 +        try:
        124 +            await sandbox.stop()
        125 +        except Exception:
        126 +            log.exception(
        127 +                "git_clone: failed to stop sandbox after clone: sandbox_id=%s",
        128 +                ctx.sandbox_id,
        129 +            )
        130 +
        131 +    log.info(
        132 +        "git_clone: ok user_id=%s repo_id=%s sandbox_id=%s",
        133 +        ctx.user_id,
        134 +        ctx.repo_id,
        135 +        ctx.sandbox_id,
        136 +    )
        137 +
        138 +
        139 +__all__ = ["git_clone_step"]
        140 +

```
