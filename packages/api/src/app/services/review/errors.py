"""Typed step errors for the review pipeline.

Each step raises a concrete :class:`StepError` subclass on failure.
Errors fall into two families:

- :class:`StepError` — the base for all step errors. Concrete subclasses
  encode the specific failure mode.

- :class:`TransientStepError` — a marker subclass of :class:`StepError`
  for failures that DBOS should retry (network blips, E2B connect
  timeouts, LLM 429 / 5xx / timeouts). Every step that wants DBOS-level
  retry installs
  ``should_retry=lambda exc: isinstance(exc, TransientStepError)`` and
  raises a :class:`TransientStepError` subclass on the relevant
  failures.

Errors that are *not* :class:`TransientStepError` are considered final
business outcomes (e.g. the PR has no active sandbox, the agent
finished but produced no structured response). They are not retried;
the workflow lets them propagate and the DBOS workflow is marked as
ERROR.

The module also exposes two helpers for LLM error handling:
:func:`is_llm_retry_error` and :func:`extract_retry_after_seconds`.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import TYPE_CHECKING, Any, TypeAlias

if TYPE_CHECKING:
    from app.core.llm import LLMConfig

log = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Base classes                                                                 #
# --------------------------------------------------------------------------- #


class StepError(Exception):
    """Base class for all durable step errors."""


class TransientStepError(StepError):
    """Marker base for transient failures DBOS should retry.

    Subclasses encode failures that are expected to clear up on a
    subsequent attempt: rate limits, network blips, sandbox connect
    timeouts, etc. Step decorators that want DBOS-managed retry should
    set ``should_retry=lambda exc: isinstance(exc, TransientStepError)``.
    """


# --------------------------------------------------------------------------- #
# Per-step concrete errors                                                     #
# --------------------------------------------------------------------------- #


class RepoNotFoundError(StepError):
    """The requested repo does not exist in the local repo table."""

    def __init__(self, repo_id: str) -> None:
        self.repo_id = repo_id
        super().__init__(f"repo {repo_id!r} not found")


class NoActiveSandboxError(StepError):
    """No active sandbox exists for the ``(user, repo)`` pair."""

    def __init__(self, user_id: str, repo_id: str) -> None:
        self.user_id = user_id
        self.repo_id = repo_id
        super().__init__(f"no active sandbox for user {user_id!r} repo {repo_id!r}")


class SandboxConnectError(TransientStepError):
    """E2B sandbox connect / IO failed; DBOS should retry the step."""

    def __init__(
        self,
        *,
        user_id: str,
        repo_id: str,
        sandbox_id: str,
        cause: str,
    ) -> None:
        self.user_id = user_id
        self.repo_id = repo_id
        self.sandbox_id = sandbox_id
        self.cause = cause
        super().__init__(f"failed to connect sandbox {sandbox_id!r}: {cause}")


class DiffUnavailableError(StepError):
    """We could not obtain a unified diff to review."""

    def __init__(
        self,
        *,
        repo_id: str,
        base_sha: str,
        head_sha: str,
        cause: str,
    ) -> None:
        self.repo_id = repo_id
        self.base_sha = base_sha
        self.head_sha = head_sha
        self.cause = cause
        super().__init__(f"diff unavailable ({base_sha}...{head_sha}): {cause}")


class ReviewAgentCrashedError(StepError):
    """The review agent raised an unexpected, non-transient exception."""

    def __init__(self, cause: str) -> None:
        self.cause = cause
        super().__init__(f"review agent crashed: {cause}")


class ReviewAgentRateLimitedError(TransientStepError):
    """The LLM returned 429 / 5xx / timeout; DBOS should retry the step."""

    def __init__(
        self,
        *,
        cause: str,
        retry_after_seconds: float | None = None,
    ) -> None:
        self.cause = cause
        self.retry_after_seconds = retry_after_seconds
        super().__init__(cause)


class ReviewAgentReturnedNoStructuredResponseError(StepError):
    """The agent finished but produced no ``structured_response`` payload."""

    def __init__(self, message_kinds: tuple[str, ...]) -> None:
        self.message_kinds = message_kinds
        super().__init__(
            "review agent returned no structured response "
            f"(messages={list(message_kinds)})"
        )


# --------------------------------------------------------------------------- #
# Per-subagent invocation errors (parallel fan-out)                            #
# --------------------------------------------------------------------------- #


class AgentInvocationError(StepError):
    """Base for a single subagent's failure during parallel fan-out.

    Raised from the ``invoke_<name>_agent`` wrappers in
    :mod:`app.services.review.steps.invoke_agent`. Each subclass
    hard-codes the value of :attr:`name` so the failure can be
    attributed to a specific specialist.

    The :attr:`retryable` flag mirrors DBOS retry semantics — when
    ``True``, the wrapping step's ``should_retry`` predicate should
    return ``True``. The flag is set by the wrapper based on whether
    the underlying exception is a transient LLM failure (429 / 5xx /
    timeout).

    Attributes:
        name: The subagent's name (``"summarizer"``, ``"security"``,
            ``"correctness"``, or ``"style"``).
        cause_exception: The original exception raised by the
            subagent's ``ainvoke`` call or its post-processing.
        retryable: ``True`` iff DBOS should retry the wrapping step.
        details: Free-form dict (e.g. ``{"message_kinds": [...]}``)
            with whatever context the wrapper could capture before the
            failure.
    """

    name: str
    cause_exception: BaseException
    retryable: bool
    details: dict[str, Any]

    def __init__(
        self,
        *,
        name: str,
        cause: BaseException,
        retryable: bool,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.name = name
        self.cause_exception = cause
        self.retryable = retryable
        self.details = details or {}
        super().__init__(f"{name} agent invocation failed: {cause!r}")


class SummaryAgentInvocationError(AgentInvocationError):
    """The ``summarizer`` subagent failed."""

    def __init__(
        self,
        *,
        cause: BaseException,
        retryable: bool,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            name="summarizer", cause=cause, retryable=retryable, details=details
        )


class SecurityAgentInvocationError(AgentInvocationError):
    """The ``security`` subagent failed."""

    def __init__(
        self,
        *,
        cause: BaseException,
        retryable: bool,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            name="security", cause=cause, retryable=retryable, details=details
        )


class CorrectnessAgentInvocationError(AgentInvocationError):
    """The ``correctness`` subagent failed."""

    def __init__(
        self,
        *,
        cause: BaseException,
        retryable: bool,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            name="correctness", cause=cause, retryable=retryable, details=details
        )


class StyleAgentInvocationError(AgentInvocationError):
    """The ``style`` subagent failed."""

    def __init__(
        self,
        *,
        cause: BaseException,
        retryable: bool,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            name="style", cause=cause, retryable=retryable, details=details
        )


# Union of the four per-subagent error classes. Use this (or
# ``type[SubagentInvocationError]``) when a callable accepts the class
# itself — e.g. the per-subagent wrappers in
# :mod:`app.services.review.steps.invoke_agent`.
SubagentInvocationError: TypeAlias = (
    SummaryAgentInvocationError
    | SecurityAgentInvocationError
    | CorrectnessAgentInvocationError
    | StyleAgentInvocationError
)


class ReviewAgentsInvocationError(StepError):
    """One or more subagents failed during parallel fan-out.

    Raised from
    :func:`app.services.review.steps.invoke_agent.invoke_review_agents_step`
    after :func:`asyncio.gather` partitions successes from failures.
    Each per-subagent error is preserved in :attr:`failed_agents`; the
    aggregate carries the full run context (user, repo, pr, head_sha,
    LLM provider/model/base URL, workflow id, and the UTC timestamp of
    the failure) so production dashboards have everything needed to
    attribute a failure without cross-referencing logs.

    The LLM-derived fields (:attr:`llm_provider`, :attr:`llm_model`,
    :attr:`llm_base_url`) are read from the :class:`LLMConfig` the
    step received, so the Sentry tags (``llm.provider``,
    ``llm.model``) and ``llm.base_url`` extra keep their existing
    names.
    """

    user_id: str
    repo_id: str
    pr_number: int
    head_sha: str
    llm_provider: str
    llm_model: str
    llm_base_url: str | None
    workflow_id: str
    failed_agents: list[AgentInvocationError]
    succeeded_agents: list[str]
    occurred_at: datetime

    def __init__(
        self,
        *,
        user_id: str,
        repo_id: str,
        pr_number: int,
        head_sha: str,
        llm_config: LLMConfig,
        workflow_id: str,
        failed_agents: list[AgentInvocationError],
        succeeded_agents: list[str],
        occurred_at: datetime,
    ) -> None:
        self.user_id = user_id
        self.repo_id = repo_id
        self.pr_number = pr_number
        self.head_sha = head_sha
        self.llm_provider = llm_config.provider
        self.llm_model = llm_config.model_id
        self.llm_base_url = llm_config.base_url
        self.workflow_id = workflow_id
        self.failed_agents = list(failed_agents)
        self.succeeded_agents = list(succeeded_agents)
        self.occurred_at = occurred_at
        names = [e.name for e in failed_agents]
        super().__init__(
            f"review agents invocation failed for pr={pr_number} "
            f"head_sha={head_sha[:7]}: failed={names} "
            f"succeeded={succeeded_agents}"
        )


# --------------------------------------------------------------------------- #
# LLM error classification                                                     #
# --------------------------------------------------------------------------- #

_RETRY_AFTER_RE = re.compile(
    r"try again in\s+(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>ms|s|m|h)?",
    re.IGNORECASE,
)
_UNIT_TO_SECONDS: dict[str, float] = {
    "ms": 0.001,
    "s": 1.0,
    "m": 60.0,
    "h": 3600.0,
}
"""Multiplier from a parsed retry-after unit string to seconds."""


def _status_code(exc: BaseException) -> int | None:
    """Return ``exc.status_code`` if it's an int, else ``None``."""
    raw = getattr(exc, "status_code", None)
    return raw if isinstance(raw, int) else None


def is_llm_retry_error(exc: BaseException) -> bool:
    """Return ``True`` iff ``exc`` is a retryable LLM failure.

    Covers OpenAI, Anthropic, and Google GenAI SDKs. Falls back to a
    ``status_code`` heuristic for wrapped exceptions. All provider
    imports are lazy so a missing SDK package never breaks import.
    """
    # OpenAI: RateLimitError / APITimeoutError / APIConnectionError /
    # APIStatusError 429|5xx.
    try:
        import openai

        if isinstance(
            exc,
            (
                openai.RateLimitError,
                openai.APITimeoutError,
                openai.APIConnectionError,
            ),
        ):
            return True
        if isinstance(exc, openai.APIStatusError):
            code = _status_code(exc)
            if code is not None and (code == 429 or 500 <= code < 600):
                return True
    except ImportError:
        pass

    # Anthropic: RateLimitError / InternalServerError / APITimeoutError /
    # APIConnectionError / APIStatusError 429|5xx.
    try:
        import anthropic

        if isinstance(
            exc,
            (
                anthropic.RateLimitError,
                anthropic.InternalServerError,
                anthropic.APITimeoutError,
                anthropic.APIConnectionError,
            ),
        ):
            return True
        if isinstance(exc, anthropic.APIStatusError):
            code = _status_code(exc)
            if code is not None and (code == 429 or 500 <= code < 600):
                return True
    except ImportError:
        pass

    # Google: ResourceExhausted (429) / ServiceUnavailable (503) /
    # DeadlineExceeded (504).
    try:
        import google.api_core.exceptions as gexc  # pyright: ignore[reportMissingImports]

        if isinstance(
            exc,
            (
                gexc.ResourceExhausted,
                gexc.ServiceUnavailable,
                gexc.DeadlineExceeded,
            ),
        ):
            return True
    except ImportError:
        pass

    # Fallback: bare ``status_code`` for wrapped / unrecognised exceptions.
    code = _status_code(exc)
    if code is not None and (code == 429 or 500 <= code < 600):
        return True

    return False


def extract_retry_after_seconds(exc: BaseException) -> float | None:
    """Parse a retry-after hint from an LLM error, in seconds.

    Tries, in order:

    1. ``response.headers.get("retry-after")`` if the exception carries a
       ``response`` with headers — accepts a numeric value (seconds).
    2. The OpenAI ``"Please try again in 372ms"`` / ``"1.2s"`` / ``"5m"``
       text in ``str(exc)``.

    Returns ``None`` when no parseable hint exists.
    """
    # 1. ``Retry-After`` header on a wrapped response.
    response = getattr(exc, "response", None)
    if response is not None:
        headers = getattr(response, "headers", None)
        if headers is not None:
            try:
                value = headers.get("retry-after")  # type: ignore[union-attr]
            except Exception:
                value = None
            if isinstance(value, (str, int, float)):
                try:
                    return float(value)
                except (TypeError, ValueError):
                    # HTTP date format; we don't parse those here.
                    pass

    # 2. OpenAI ``"Please try again in Xms"`` hint.
    match = _RETRY_AFTER_RE.search(str(exc))
    if match is None:
        return None
    try:
        value = float(match.group("value"))
    except (TypeError, ValueError):
        return None
    unit = (match.group("unit") or "s").lower()
    return value * _UNIT_TO_SECONDS.get(unit, 1.0)


__all__ = [
    "AgentInvocationError",
    "CorrectnessAgentInvocationError",
    "DiffUnavailableError",
    "NoActiveSandboxError",
    "RepoNotFoundError",
    "ReviewAgentCrashedError",
    "ReviewAgentRateLimitedError",
    "ReviewAgentReturnedNoStructuredResponseError",
    "ReviewAgentsInvocationError",
    "SandboxConnectError",
    "SecurityAgentInvocationError",
    "StepError",
    "StyleAgentInvocationError",
    "SubagentInvocationError",
    "SummaryAgentInvocationError",
    "TransientStepError",
    "extract_retry_after_seconds",
    "is_llm_retry_error",
]
