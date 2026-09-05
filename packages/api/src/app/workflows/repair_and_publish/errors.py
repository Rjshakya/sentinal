"""Typed errors for the repair-and-publish workflow.

Following the review-pipeline conventions:

**Error values** (subclasses of :class:`RepairPublishError`) — plain
Pydantic models *returned* (never raised) by the package's pure step
functions. Each carries a ``retryable`` flag plus the branded run
identity so the DBOS step edge can decide what to do without re-reading
anything.

**Raised step exceptions** (:class:`RepairPublishStepFailure` /
:class:`TransientRepairPublishStepFailure`) — the only exceptions the
DBOS step edges raise. They wrap the error value so the shared
:func:`shouldRetry` predicate discriminates on
:class:`TransientRepairPublishStepFailure` and DBOS retries the step.
"""

from __future__ import annotations

from pydantic import BaseModel

from app.utils.branded import PRNumber, RepoId, ReviewRowId


class RepairPublishError(BaseModel):
    """Base error value returned by the package's pure step functions.

    ``retryable=True`` means the DBOS step edge should raise
    :class:`TransientRepairPublishStepFailure` so DBOS retries the
    step; ``retryable=False`` means a business outcome that propagates
    as a :class:`RepairPublishStepFailure` (or is handled by the
    workflow).
    """

    message: str
    retryable: bool = False
    reviewId: ReviewRowId | None = None
    repoId: RepoId | None = None
    prNumber: PRNumber | None = None

    def __str__(self) -> str:
        return self.message


class CheckError(RepairPublishError):
    """The unpublished-review check failed (DB / config problem).

    The business skips (no review row, no summary, already published)
    are **not** errors — they surface as ``None`` from the check step,
    per the step contract.
    """


class DeleteRepoError(RepairPublishError):
    """Removing the cloned repo from the sandbox failed.

    Best-effort cleanup — the step edge logs and continues, never
    raising: a cleanup failure must not mask the run's outcome.
    """


class PublishError(RepairPublishError):
    """The repair agent (model build, sandbox reconnect, or LLM call)
    failed."""


class SaveError(RepairPublishError):
    """The GitHub back-link rows could not be written."""


class RepairPublishStepFailure(Exception):
    """Raised by a DBOS step edge for a final (business) error value.

    Carries the underlying :class:`RepairPublishError` so the workflow
    can unwrap it.
    """

    def __init__(self, error: RepairPublishError) -> None:
        self.error = error
        super().__init__(error.message)


class TransientRepairPublishStepFailure(RepairPublishStepFailure):
    """Raised by a DBOS step edge for a retryable error value.

    :func:`shouldRetry` checks this type, so DBOS retries the step
    (``max_attempts`` times with backoff) before the exception
    propagates to the workflow.
    """


def shouldRetry(exc: BaseException) -> bool:
    """Shared ``should_retry`` predicate for the package's durable steps."""
    return isinstance(exc, TransientRepairPublishStepFailure)


__all__ = [
    "CheckError",
    "DeleteRepoError",
    "PublishError",
    "RepairPublishError",
    "RepairPublishStepFailure",
    "SaveError",
    "TransientRepairPublishStepFailure",
    "shouldRetry",
]
