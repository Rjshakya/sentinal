"""Typed errors for the review workflow.

Two layers, following the new service conventions:

**Error values** (subclasses of :class:`ReviewStepError`) — plain
Pydantic models *returned* (never raised) by the pure step functions.
Each carries a ``retryable`` flag plus the branded run identity so the
DBOS step edge can decide what to do without re-reading anything.

**Raised step exceptions** (:class:`ReviewStepFailure` /
:class:`TransientReviewStepFailure`) — the only exceptions the DBOS
step edges raise. They wrap the error value (:attr:`ReviewStepFailure.error`)
so ``should_retry`` predicates discriminate on
:class:`TransientReviewStepFailure` and the workflow's error-context
builder can unwrap the underlying value.

The module also owns :func:`isLlmRetryError` (the provider-agnostic
LLM transient-failure classifier) and :func:`isRetryableStatusCode`
(GitHub/HTTP transient-status classifier), both pure.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel

from app.utils.branded import (
    CommitId,
    PRNumber,
    RepoId,
    RepoName,
    RepoOwner,
    UserId,
)

AgentLane = Literal["summarizer", "comments"]
"""The two review-agent lanes, in the deterministic gather order."""


# --------------------------------------------------------------------------- #
# Error values                                                                 #
# --------------------------------------------------------------------------- #


class ReviewStepError(BaseModel):
    """Base error value returned by pure step functions.

    ``retryable=True`` means the DBOS step edge should raise
    :class:`TransientReviewStepFailure` so DBOS retries the step;
    ``retryable=False`` means a business outcome that propagates as a
    :class:`ReviewStepFailure` (or is handled by the workflow).
    """

    message: str
    retryable: bool = False
    userId: UserId | None = None
    repoId: RepoId | None = None
    prNumber: PRNumber | None = None
    headSha: CommitId | None = None

    def __str__(self) -> str:
        return self.message


class RepoGetError(ReviewStepError):
    """The repo has no local ``repos`` row for the GitHub repo id."""


class SandboxCreateError(ReviewStepError):
    """The per-run ephemeral sandbox could not be created.

    Transient: the step retry creates a fresh sandbox.
    """

    retryable: bool = True


class SandboxConnectError(ReviewStepError):
    """Reconnect to the run's sandbox by id failed. Transient."""

    retryable: bool = True


class CloneError(ReviewStepError):
    """``git clone`` (or the PR-head ref fetch) failed.

    Business outcome: bad token, missing repo, transport error.
    """

    exitCode: int | None = None
    outputTail: str | None = None


class CloneTransientError(CloneError):
    """Token mint / sandbox reconnect / runner dropout. Transient."""

    retryable: bool = True


class DiffUnavailableError(ReviewStepError):
    """``git diff`` (or ``mkdir``) returned a non-zero exit code."""

    baseSha: CommitId | None = None


class DiffSplitError(ReviewStepError):
    """The split script exited non-zero or printed no parseable summary."""


class DiffSplitSetupError(ReviewStepError):
    """Split-script upload failed or the runner dropped the run. Transient."""

    retryable: bool = True


class UpsertPRError(ReviewStepError):
    """The ``pull_requests`` row could not be inserted or updated."""


class LifecycleUpdateError(ReviewStepError):
    """A ``review`` lifecycle-row write failed. Transient."""

    retryable: bool = True


class PersistError(ReviewStepError):
    """A summary / comments / usage row could not be persisted."""


class AgentLaneError(ReviewStepError):
    """One research lane (or its extractor) failed.

    ``lane`` names the failing lane; ``retryable`` mirrors whether the
    underlying failure was transient (LLM 429 / 5xx / timeout, sandbox
    blip) so the step edge can retry that lane alone.
    """

    lane: AgentLane


class ExtractionError(AgentLaneError):
    """The structured extractor failed for a lane.

    Transient LLM failures carry ``retryable=True``; a schema mismatch
    or empty input is a business outcome that degrades the lane.
    """


class PostReviewError(ReviewStepError):
    """Posting the review to GitHub failed.

    ``statusCode`` drives :func:`isRetryableStatusCode` at the edge:
    retryable (429 / 5xx) errors retry the step; other statuses are
    returned to the workflow as a ``posted=False`` outcome so the
    review still completes locally.
    """

    statusCode: int | None = None


class ReviewAgentsError(ReviewStepError):
    """Both research lanes failed (research or extraction).

    Raised by the workflow body (wrapped in
    :class:`ReviewStepFailure`) after each lane exhausted its own step
    retries, carrying the per-lane failures and the lanes that
    succeeded.
    """

    failedLanes: list[AgentLaneError]
    succeededLanes: list[AgentLane]


# --------------------------------------------------------------------------- #
# Raised step exceptions (the DBOS edge)                                       #
# --------------------------------------------------------------------------- #


class ReviewStepFailure(Exception):
    """Raised by a DBOS step edge for a final (business) error value.

    Carries the underlying :class:`ReviewStepError` so the workflow's
    ``except`` block and error-context builder can unwrap it.
    """

    def __init__(self, error: ReviewStepError) -> None:
        self.error = error
        super().__init__(error.message)


class TransientReviewStepFailure(ReviewStepFailure):
    """Raised by a DBOS step edge for a retryable error value.

    ``should_retry`` predicates check this type, so DBOS retries the
    step (``max_attempts`` times with backoff) before the exception
    propagates to the workflow.
    """


def shouldRetry(exc: BaseException) -> bool:
    """Shared ``should_retry`` predicate for durable steps."""
    return isinstance(exc, TransientReviewStepFailure)


# --------------------------------------------------------------------------- #
# Transient-failure classifiers                                                #
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


def _statusCode(exc: BaseException) -> int | None:
    """Return ``exc.status_code`` when it is an int, else ``None``."""
    raw = getattr(exc, "status_code", None)
    return raw if isinstance(raw, int) else None


def isLlmRetryError(exc: BaseException) -> bool:
    """Return ``True`` iff ``exc`` is a retryable LLM failure.

    Covers OpenAI, Anthropic, and Google GenAI SDKs, falling back to a
    ``status_code`` heuristic for wrapped exceptions. Provider imports
    are lazy so a missing SDK package never breaks import.
    """
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
            code = _statusCode(exc)
            if code is not None and (code == 429 or 500 <= code < 600):
                return True
    except ImportError:
        pass

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
            code = _statusCode(exc)
            if code is not None and (code == 429 or 500 <= code < 600):
                return True
    except ImportError:
        pass

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

    code = _statusCode(exc)
    return code is not None and (code == 429 or 500 <= code < 600)


def extractRetryAfterSeconds(exc: BaseException) -> float | None:
    """Parse a retry-after hint from an LLM error, in seconds.

    Tries the ``Retry-After`` response header first, then the OpenAI
    ``"Please try again in 372ms"`` text hint. Returns ``None`` when no
    parseable hint exists.
    """
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
                    pass

    match = _RETRY_AFTER_RE.search(str(exc))
    if match is None:
        return None
    try:
        value = float(match.group("value"))
    except (TypeError, ValueError):
        return None
    unit = (match.group("unit") or "s").lower()
    return value * _UNIT_TO_SECONDS.get(unit, 1.0)


def isRetryableStatusCode(statusCode: int | None) -> bool:
    """Return ``True`` iff ``statusCode`` is a retryable HTTP status.

    429 (rate limit) and 5xx (server-side) failures are transient; 4xx
    are business outcomes.
    """
    return statusCode is not None and (statusCode == 429 or 500 <= statusCode < 600)


__all__ = [
    "AgentLane",
    "AgentLaneError",
    "CloneError",
    "CloneTransientError",
    "DiffSplitError",
    "DiffSplitSetupError",
    "DiffUnavailableError",
    "ExtractionError",
    "LifecycleUpdateError",
    "PersistError",
    "PostReviewError",
    "RepoGetError",
    "ReviewAgentsError",
    "ReviewStepError",
    "ReviewStepFailure",
    "SandboxConnectError",
    "SandboxCreateError",
    "TransientReviewStepFailure",
    "UpsertPRError",
    "extractRetryAfterSeconds",
    "isLlmRetryError",
    "isRetryableStatusCode",
    "shouldRetry",
]