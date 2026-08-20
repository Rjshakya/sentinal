### packages/api/src/app/services/indexing/errors.py

```diff

index 4a9e90d..7c01b46 100644
--- a/packages/api/src/app/services/indexing/errors.py
+++ b/packages/api/src/app/services/indexing/errors.py
@@ -14,7 +14,7 @@ The retry policy at every ``@DBOS.step`` is::
   15    15  
   16    16  so a step only re-runs when the exception it raises inherits from
   17    17  :class:`TransientIndexingError`. The hierarchy mirrors
   18       -:mod:`app.services.setup.errors` but is named
         18 +:mod:`app.services.agent.setup_workflow.errors` but is named
   19    19  independently, per that module's convention.
   20    20  
   21    21  The single :func:`run_index_step` replaces the legacy
@@ -30,8 +30,6 @@ from __future__ import annotations
   31    31  __all__ = [
   32    32      "IndexGitCloneError",
   33    33      "IndexGitCloneTransientError",
   34       -    "IndexInstallTokenMintError",
   35       -    "IndexInstallationNotFoundError",
   36    34      "IndexRunError",
   37    35      "IndexRunTransientError",
   38    36      "IndexSandboxConnectError",
@@ -133,42 +131,6 @@ class IndexGitCloneTransientError(TransientIndexingError):
  134   132          super().__init__(message or f"git clone transient sandbox failure: {cause}")
  135   133  
  136   134  
  137       -class IndexInstallationNotFoundError(IndexingError):
  138       -    """No :class:`Installation` row matches ``(user_id, account_login)``.
  139       -
  140       -    Final — the repo's installation is missing from the local
  141       -    ``installations`` table (or was deleted), so no installation
  142       -    token can be minted and no authenticated clone URL can be built.
  143       -    """
  144       -
  145       -    def __init__(
  146       -        self,
  147       -        message: str | None = None,
  148       -        *,
  149       -        user_id: str = "",
  150       -        repo_owner: str = "",
  151       -        repo_name: str = "",
  152       -    ) -> None:
  153       -        self.user_id = user_id
  154       -        self.repo_owner = repo_owner
  155       -        self.repo_name = repo_name
  156       -        super().__init__(
  157       -            message
  158       -            or f"no installation found for user_id={user_id} owner={repo_owner} "
  159       -            f"repo={repo_name}"
  160       -        )
  161       -
  162       -
  163       -class IndexInstallTokenMintError(TransientIndexingError):
  164       -    """Minting the installation access token failed. DBOS retries."""
  165       -
  166       -    def __init__(self, message: str | None = None, *, cause: str = "") -> None:
  167       -        self.cause = cause
  168       -        super().__init__(
  169       -            message or f"installation token mint failed: {cause}"
  170       -        )
  171       -
  172       -
  173   135  class ScriptSetupError(TransientIndexingError):
  174   136      """Writing the chunking / ingestion scripts into the sandbox failed.
  175   137  

```
