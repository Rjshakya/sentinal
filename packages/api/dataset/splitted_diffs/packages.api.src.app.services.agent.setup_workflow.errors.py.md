### packages/api/src/app/services/agent/setup_workflow/errors.py

```diff

new file mode 100644
index 0000000..380b030
--- /dev/null
+++ b/packages/api/src/app/services/agent/setup_workflow/errors.py
@@ -0,0 +1,164 @@
          2 +"""Typed step errors for the setup pipeline.
          3 +
          4 +Every error raised inside a :func:`@DBOS.step` is a subclass of
          5 +:class:`SetupError`. The marker base :class:`TransientSetupError`
          6 +identifies failures that DBOS should retry (network blips, LLM 429 / 5xx
          7 +/ timeouts, E2B connect dropouts). Everything else is a final business
          8 +outcome: a bad install token, a missing repo, an agent that crashed
          9 +non-transiently.
         10 +
         11 +The setup pipeline's retry policy at every ``@DBOS.step`` is::
         12 +
         13 +    should_retry=lambda exc: isinstance(exc, TransientSetupError)
         14 +
         15 +so a step only re-runs when the exception it raises inherits from
         16 +:class:`TransientSetupError`. Plain :class:`SetupError` subclasses
         17 +short-circuit the workflow; DBOS marks the workflow ``ERROR`` and the
         18 +router surfaces the failure through the workflow's
         19 +:class:`SetupWorkflowResult` (``error_name`` / ``error_message``).
         20 +
         21 +The hierarchy mirrors :mod:`app.services.review.errors` but is named
         22 +independently (``SetupError`` vs ``StepError``) so a future shared
         23 +base is a clean refactor rather than a rename across two pipelines.
         24 +"""
         25 +
         26 +from __future__ import annotations
         27 +
         28 +from typing import Optional
         29 +
         30 +
         31 +class SetupError(Exception):
         32 +    """Base class for every setup-pipeline step error."""
         33 +
         34 +
         35 +class TransientSetupError(SetupError):
         36 +    """Marker base for transient failures DBOS should retry.
         37 +
         38 +    Subclasses encode failures that are expected to clear up on a
         39 +    subsequent attempt: GitHub install-token mint transient failures,
         40 +    E2B connect / IO dropouts, LLM 429 / 5xx / timeouts. Step
         41 +    decorators that want DBOS-managed retry should set
         42 +    ``should_retry=lambda exc: isinstance(exc, TransientSetupError)``.
         43 +    """
         44 +
         45 +
         46 +class InstallationNotFoundError(SetupError):
         47 +    """The user's :class:`app.models.installation.Installation` row is missing
         48 +    or owned by a different user. Final — not retried.
         49 +    """
         50 +
         51 +    def __init__(self, *, installation_id: str, user_id: str) -> None:
         52 +        self.installation_id = installation_id
         53 +        self.user_id = user_id
         54 +        super().__init__(
         55 +            f"installation_id={installation_id!r} does not belong to "
         56 +            f"user_id={user_id!r}"
         57 +        )
         58 +
         59 +
         60 +class SandboxCreateError(TransientSetupError):
         61 +    """E2B sandbox creation failed transiently. DBOS retries the step.
         62 +
         63 +    The retry re-runs the entire :func:`ensure_repo_and_sandbox_step`
         64 +    (idempotent for the DB upserts, fresh for the E2B call). On a
         65 +    persistent failure the workflow records the cause in
         66 +    :class:`SetupWorkflowResult.error_message`.
         67 +    """
         68 +
         69 +    def __init__(self, cause: str) -> None:
         70 +        self.cause = cause
         71 +        super().__init__(f"sandbox create failed: {cause}")
         72 +
         73 +
         74 +class InstallTokenMintError(TransientSetupError):
         75 +    """Minting a GitHub installation token failed transiently.
         76 +
         77 +    Wraps the underlying ``githubkit`` / ``mint_installation_token``
         78 +    exception. DBOS retries the step; on persistent failure the
         79 +    workflow surfaces the cause through
         80 +    :class:`SetupWorkflowResult.error_message`.
         81 +    """
         82 +
         83 +    def __init__(self, cause: str) -> None:
         84 +        self.cause = cause
         85 +        super().__init__(f"install_token_mint failed: {cause}")
         86 +
         87 +
         88 +class GitCloneError(SetupError):
         89 +    """``git clone`` inside the sandbox exited non-zero.
         90 +
         91 +    Final — not retried. The most common causes are a stale or
         92 +    revoked install token, a private repo the App no longer has
         93 +    access to, a renamed/moved repo, or a transport error that E2B
         94 +    already surfaced as a non-zero exit code. None of these clear up
         95 +    on a second attempt.
         96 +    """
         97 +
         98 +    def __init__(self, *, exit_code: int, output_tail: str) -> None:
         99 +        self.exit_code = exit_code
        100 +        self.output_tail = output_tail
        101 +        super().__init__(f"git clone failed (exit_code={exit_code}): {output_tail}")
        102 +
        103 +
        104 +class GitCloneTransientError(TransientSetupError):
        105 +    """The sandbox became unavailable mid-clone (E2B dropped the connection).
        106 +
        107 +    Retried by DBOS. The clone step reconnects via
        108 +    :meth:`E2BSandbox.connect` and re-runs the command, so a
        109 +    transient disconnect does not require a fresh sandbox.
        110 +    """
        111 +
        112 +    def __init__(self, cause: str) -> None:
        113 +        self.cause = cause
        114 +        super().__init__(f"git clone transient sandbox failure: {cause}")
        115 +
        116 +
        117 +class SetupAgentCrashedError(SetupError):
        118 +    """The setup agent raised an unexpected, non-transient exception.
        119 +
        120 +    Final — not retried. Anything that is not classified as a
        121 +    transient LLM error by :func:`app.services.review.errors.is_llm_retry_error`
        122 +    lands here. The workflow re-raises and DBOS records the
        123 +    error name + message on the workflow result.
        124 +    """
        125 +
        126 +    def __init__(self, cause: str) -> None:
        127 +        self.cause = cause
        128 +        super().__init__(f"setup agent crashed: {cause}")
        129 +
        130 +
        131 +class SetupAgentRateLimitedError(TransientSetupError):
        132 +    """The LLM returned 429 / 5xx / a timeout. Retried by DBOS."""
        133 +
        134 +    def __init__(self, cause: str, retry_after_seconds: Optional[float] = None) -> None:
        135 +        self.cause = cause
        136 +        self.retry_after_seconds = retry_after_seconds
        137 +        super().__init__(cause)
        138 +
        139 +
        140 +class SetupAgentNoStructuredResponseError(SetupError):
        141 +    """The agent ran to completion but produced no ``structured_response``
        142 +    payload the caller could deserialize. Final — not retried. The
        143 +    agent's transcript is included for diagnosis.
        144 +    """
        145 +
        146 +    def __init__(self, message_kinds: tuple[str, ...]) -> None:
        147 +        self.message_kinds = message_kinds
        148 +        super().__init__(
        149 +            "setup agent returned no structured response "
        150 +            f"(messages={list(message_kinds)})"
        151 +        )
        152 +
        153 +
        154 +__all__ = [
        155 +    "GitCloneError",
        156 +    "GitCloneTransientError",
        157 +    "InstallTokenMintError",
        158 +    "InstallationNotFoundError",
        159 +    "SandboxCreateError",
        160 +    "SetupAgentCrashedError",
        161 +    "SetupAgentNoStructuredResponseError",
        162 +    "SetupAgentRateLimitedError",
        163 +    "SetupError",
        164 +    "TransientSetupError",
        165 +]

```
