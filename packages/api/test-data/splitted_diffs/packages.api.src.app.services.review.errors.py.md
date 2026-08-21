### packages/api/src/app/services/review/errors.py

```diff

index a1431e9..83cc814 100644
--- a/packages/api/src/app/services/review/errors.py
+++ b/packages/api/src/app/services/review/errors.py
@@ -114,16 +114,6 @@ class DiffUnavailableError(StepError):
  115   115          super().__init__(f"diff unavailable ({base_sha}...{head_sha}): {cause}")
  116   116  
  117   117  
  118       -class RepoUpdateError(StepError):
  119       -    """The sandbox repo could not be refreshed to the default branch."""
  120       -
  121       -    def __init__(self, *, repo_id: str, branch: str, cause: str) -> None:
  122       -        self.repo_id = repo_id
  123       -        self.branch = branch
  124       -        self.cause = cause
  125       -        super().__init__(f"repo update failed (branch={branch!r}): {cause}")
  126       -
  127       -
  128   118  class ReviewAgentCrashedError(StepError):
  129   119      """The review agent raised an unexpected, non-transient exception."""
  130   120  
@@ -146,17 +136,6 @@ class ReviewAgentRateLimitedError(TransientStepError):
  147   137          super().__init__(cause)
  148   138  
  149   139  
  150       -class ReviewRunUpdateError(TransientStepError):
  151       -    """The ``review`` lifecycle row could not be written/updated.
  152       -
  153       -    Raised by the ``mark_review_*`` steps in
  154       -    :mod:`app.services.review.steps.review_run_steps` when the DB write
  155       -    (or the row lookup) fails. Transient — DBOS retries the step up to
  156       -    3 attempts; after that the error propagates and the workflow is
  157       -    marked ERROR.
  158       -    """
  159       -
  160       -
  161   140  # --------------------------------------------------------------------------- #
  162   141  # Per-subagent invocation errors (parallel fan-out)                            #
  163   142  # --------------------------------------------------------------------------- #
@@ -452,11 +431,9 @@ __all__ = [
  453   432      "DiffUnavailableError",
  454   433      "NoActiveSandboxError",
  455   434      "RepoNotFoundError",
  456       -    "RepoUpdateError",
  457   435      "ReviewAgentCrashedError",
  458   436      "ReviewAgentRateLimitedError",
  459   437      "ReviewAgentsInvocationError",
  460       -    "ReviewRunUpdateError",
  461   438      "SandboxConnectError",
  462   439      "StepError",
  463   440      "SubagentInvocationError",

```
