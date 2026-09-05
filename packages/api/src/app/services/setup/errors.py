"""Typed step errors for the setup pipeline.

Every error raised inside a :func:`@DBOS.step` is a subclass of
:class:`SetupError`. The marker base :class:`TransientSetupError`
identifies failures that DBOS should retry (network blips, LLM 429 / 5xx
/ timeouts, E2B connect dropouts). Everything else is a final business
outcome: a bad install token, a missing repo, an agent that crashed
non-transiently.

The setup pipeline's retry policy at every ``@DBOS.step`` is::

    should_retry=lambda exc: isinstance(exc, TransientSetupError)

so a step only re-runs when the exception it raises inherits from
:class:`TransientSetupError`. Plain :class:`SetupError` subclasses
short-circuit the workflow; DBOS marks the workflow ``ERROR`` and the
router surfaces the failure through the workflow's
:class:`SetupWorkflowResult` (``error_name`` / ``error_message``).

The hierarchy mirrors :mod:`app.workflows.review.errors` but is named
independently (``SetupError`` vs ``ReviewStepError``) so a future shared
base is a clean refactor rather than a rename across two pipelines.
"""

from __future__ import annotations

from typing import Optional


class SetupError(Exception):
    """Base class for every setup-pipeline step error."""


class TransientSetupError(SetupError):
    """Marker base for transient failures DBOS should retry.

    Subclasses encode failures that are expected to clear up on a
    subsequent attempt: GitHub install-token mint transient failures,
    E2B connect / IO dropouts, LLM 429 / 5xx / timeouts. Step
    decorators that want DBOS-managed retry should set
    ``should_retry=lambda exc: isinstance(exc, TransientSetupError)``.
    """


class InstallationNotFoundError(SetupError):
    """The user's :class:`app.models.installation.Installation` row is missing
    or owned by a different user. Final — not retried.
    """

    def __init__(self, *, installation_id: str, user_id: str) -> None:
        self.installation_id: str = installation_id
        self.user_id: str = user_id
        super().__init__(
            f"installation_id={installation_id!r} does not belong to "
            f"user_id={user_id!r}"
        )


class SandboxCreateError(TransientSetupError):
    """E2B sandbox creation failed transiently. DBOS retries the step.

    The retry re-runs the entire :func:`ensure_repo_and_sandbox_step`
    (idempotent for the DB upserts, fresh for the E2B call). On a
    persistent failure the workflow records the cause in
    :class:`SetupWorkflowResult.error_message`.
    """

    def __init__(self, cause: str) -> None:
        self.cause: str = cause
        super().__init__(f"sandbox create failed: {cause}")


class InstallTokenMintError(TransientSetupError):
    """Minting a GitHub installation token failed transiently.

    Wraps the underlying ``githubkit`` / ``mint_installation_token``
    exception. DBOS retries the step; on persistent failure the
    workflow surfaces the cause through
    :class:`SetupWorkflowResult.error_message`.
    """

    def __init__(self, cause: str) -> None:
        self.cause: str = cause
        super().__init__(f"install_token_mint failed: {cause}")


class GitCloneError(SetupError):
    """``git clone`` inside the sandbox exited non-zero.

    Final — not retried. The most common causes are a stale or
    revoked install token, a private repo the App no longer has
    access to, a renamed/moved repo, or a transport error that E2B
    already surfaced as a non-zero exit code. None of these clear up
    on a second attempt.
    """

    def __init__(self, *, exit_code: int, output_tail: str) -> None:
        self.exit_code: int = exit_code
        self.output_tail: str = output_tail
        super().__init__(f"git clone failed (exit_code={exit_code}): {output_tail}")


class GitCloneTransientError(TransientSetupError):
    """The sandbox became unavailable mid-clone (E2B dropped the connection).

    Retried by DBOS. The clone step reconnects via
    :meth:`E2BSandbox.connect` and re-runs the command, so a
    transient disconnect does not require a fresh sandbox.
    """

    def __init__(self, cause: str) -> None:
        self.cause: str = cause
        super().__init__(f"git clone transient sandbox failure: {cause}")


class SetupAgentCrashedError(SetupError):
    """The setup agent raised an unexpected, non-transient exception.

    Final — not retried. Anything that is not classified as a
    transient LLM error by :func:`app.workflows.review.errors.isLlmRetryError`
    lands here. The workflow re-raises and DBOS records the
    error name + message on the workflow result.
    """

    def __init__(self, cause: str) -> None:
        self.cause: str = cause
        super().__init__(f"setup agent crashed: {cause}")


class SetupAgentRateLimitedError(TransientSetupError):
    """The LLM returned 429 / 5xx / a timeout. Retried by DBOS."""

    def __init__(self, cause: str, retry_after_seconds: Optional[float] = None) -> None:
        self.cause: str = cause
        self.retry_after_seconds: Optional[float] = retry_after_seconds
        super().__init__(cause)


class SetupAgentNoStructuredResponseError(SetupError):
    """The agent ran to completion but produced no ``structured_response``
    payload the caller could deserialize. Final — not retried. The
    agent's transcript is included for diagnosis.
    """

    def __init__(self, message_kinds: tuple[str, ...]) -> None:
        self.message_kinds: tuple[str, ...] = message_kinds
        super().__init__(
            "setup agent returned no structured response "
            f"(messages={list(message_kinds)})"
        )


__all__ = [
    "GitCloneError",
    "GitCloneTransientError",
    "InstallTokenMintError",
    "InstallationNotFoundError",
    "SandboxCreateError",
    "SetupAgentCrashedError",
    "SetupAgentNoStructuredResponseError",
    "SetupAgentRateLimitedError",
    "SetupError",
    "TransientSetupError",
]
