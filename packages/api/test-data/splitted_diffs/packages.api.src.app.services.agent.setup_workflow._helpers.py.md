### packages/api/src/app/services/agent/setup_workflow/_helpers.py

```diff

new file mode 100644
index 0000000..9affe2b
--- /dev/null
+++ b/packages/api/src/app/services/agent/setup_workflow/_helpers.py
@@ -0,0 +1,86 @@
          2 +"""Pure helpers for the setup pipeline.
          3 +
          4 +No I/O, no session, no clock, no settings reads. Every function in
          5 +this module is testable with ``assert f(x) == y``.
          6 +
          7 +The previous implementation lived inside
          8 +``app.services.agent.setup_pipeline``; this module is the clean-room
          9 +replacement that the new DBOS workflow imports.
         10 +"""
         11 +
         12 +from __future__ import annotations
         13 +
         14 +from app.core.sandbox.types import CommandResult
         15 +from app.services.agent.setup_workflow.errors import (
         16 +    GitCloneError,
         17 +    GitCloneTransientError,
         18 +)
         19 +
         20 +
         21 +__all__ = [
         22 +    "build_authenticated_clone_url",
         23 +    "check_git_clone_result",
         24 +    "truncate_command_output",
         25 +]
         26 +
         27 +
         28 +def build_authenticated_clone_url(
         29 +    *, install_token: str, owner: str, name: str
         30 +) -> str:
         31 +    """Build the authenticated HTTPS clone URL.
         32 +
         33 +    GitHub's recommended way to authenticate ``git`` operations from
         34 +    CI: embed the install token as the basic-auth user
         35 +    (``x-access-token:<token>``). Works for both public and private
         36 +    repos. The token grants exactly the scopes the GitHub App was
         37 +    installed with, so this is the right primitive for cloning on the
         38 +    user's behalf.
         39 +    """
         40 +    return f"https://x-access-token:{install_token}@github.com/{owner}/{name}.git"
         41 +
         42 +
         43 +def truncate_command_output(result: CommandResult, *, max_chars: int = 500) -> str:
         44 +    """Take a :class:`CommandResult` and return a short string tail.
         45 +
         46 +    Prefers ``stderr`` (which usually has the failure cause), falls
         47 +    back to ``stdout``, strips whitespace, and truncates to
         48 +    ``max_chars``. The output is meant to be embedded in
         49 +    :class:`GitCloneError`'s ``output_tail`` — keep it short.
         50 +    """
         51 +    raw = (result.stderr or result.stdout or "").strip()
         52 +    return raw[:max_chars]
         53 +
         54 +
         55 +def check_git_clone_result(result: CommandResult) -> None:
         56 +    """Raise the appropriate typed error for a non-success clone result.
         57 +
         58 +    The :meth:`BaseSandbox.execute` contract reports a sandbox-level
         59 +    failure as ``exit_code == -1`` with the cause in
         60 +    :attr:`CommandResult.error`; a real ``git`` failure is
         61 +    ``exit_code > 0`` with the cause in :attr:`CommandResult.stderr`.
         62 +    This helper maps both into the typed error hierarchy so the
         63 +    calling step can let one ``except`` block handle them::
         64 +
         65 +        try:
         66 +            clone = await sandbox.execute("git clone …")
         67 +            check_git_clone_result(clone)
         68 +        except GitCloneTransientError:
         69 +            # DBOS retries (TransientSetupError)
         70 +            raise
         71 +        except GitCloneError:
         72 +            # Final, do not retry
         73 +            raise
         74 +
         75 +    - ``exit_code == 0``  → return (no error).
         76 +    - ``exit_code == -1`` → raise :class:`GitCloneTransientError`
         77 +      (sandbox disconnect / command runner failure).
         78 +    - ``exit_code > 0``   → raise :class:`GitCloneError` (real
         79 +      git failure: bad token, missing repo, network, etc.).
         80 +    """
         81 +    if result.exit_code == 0:
         82 +        return
         83 +    tail = truncate_command_output(result)
         84 +    if result.exit_code == -1:
         85 +        raise GitCloneTransientError(cause=tail or "sandbox command runner failure")
         86 +    raise GitCloneError(exit_code=result.exit_code, output_tail=tail)
         87 +

```
