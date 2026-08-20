### packages/api/src/app/services/indexing/steps/git_clone.py

```diff

index 26d9a5b..c3efc6e 100644
--- a/packages/api/src/app/services/indexing/steps/git_clone.py
+++ b/packages/api/src/app/services/indexing/steps/git_clone.py
@@ -9,7 +9,7 @@ failure).
   10    10  
   11    11  DBOS keys step registration on ``__name__``. Named ``gitCloneToSandbox``
   12    12  to avoid colliding with the setup pipeline's own ``git_clone_step``
   13       -in :mod:`app.services.setup.steps`.
         13 +in :mod:`app.services.agent.setup_workflow`.
   14    14  """
   15    15  
   16    16  from __future__ import annotations
@@ -37,18 +37,12 @@ CLONE_TIMEOUT_S: float = 300.0
   38    38  """Upper bound on the wall-clock duration of a single ``git clone``."""
   39    39  
   40    40  
   41       -def build_clone_command(ctx: IndexContext, *, clone_url: str | None = None) -> str:
   42       -    """Build the shell command for the sandbox (pure, testable).
   43       -
   44       -    ``clone_url`` overrides :attr:`IndexContext.repo_url` — the
   45       -    authenticated URL resolved by :func:`getRepoUrl` (private-repo
   46       -    support). Falls back to the plain ``repo_url`` from the input
   47       -    when no override is given.
   48       -    """
         41 +def build_clone_command(ctx: IndexContext) -> str:
         42 +    """Build the shell command for the sandbox (pure, testable)."""
   49    43      parts = ["git", "clone", "--depth", "1"]
   50    44      if ctx.default_branch:
   51    45          parts += ["--single-branch", "--branch", ctx.default_branch]
   52       -    parts += [clone_url or ctx.repo_url, ctx.repo_name]
         46 +    parts += [ctx.repo_url, ctx.repo_name]
   53    47      return " ".join(shlex.quote(part) for part in parts)
   54    48  
   55    49  
@@ -69,18 +63,12 @@ def check_git_clone(result: CommandResult) -> None:
   70    64      max_attempts=3,
   71    65      should_retry=_should_retry_index,
   72    66  )
   73       -async def gitCloneToSandbox(
   74       -    *,
   75       -    ctx: IndexContext,
   76       -    clone_url: str | None = None,
   77       -) -> None:
         67 +async def gitCloneToSandbox(*, ctx: IndexContext) -> None:
   78    68      """Shallow-clone ``ctx.repo_url`` into the sandbox workspace.
   79    69  
   80       -    ``clone_url`` overrides ``ctx.repo_url`` — the authenticated URL
   81       -    resolved by :func:`getRepoUrl` for private repos. Reconnects to
   82       -    the sandbox by id. Reconnect failures and runner dropouts raise
   83       -    transient errors (DBOS retries); a real ``git`` failure (bad URL,
   84       -    auth, missing repo) is final.
         70 +    Reconnects to the sandbox by id. Reconnect failures and runner
         71 +    dropouts raise transient errors (DBOS retries); a real ``git``
         72 +    failure (bad URL, auth, missing repo) is final.
   85    73      """
   86    74      try:
   87    75          sandbox: E2BSandbox = await connect_index_sandbox(ctx)
@@ -89,7 +77,7 @@ async def gitCloneToSandbox(
   90    78          # Mirror the setup pipeline, which creates it before cloning.
   91    79          await sandbox.fs_create_folder(workspace_path())
   92    80          result = await sandbox.execute(
   93       -            build_clone_command(ctx, clone_url=clone_url),
         81 +            build_clone_command(ctx),
   94    82              cwd=workspace_path(),
   95    83              timeout=CLONE_TIMEOUT_S,
   96    84          )

```
