"""Fresh v3 step errors: values returned, never raised.

Each step returns ``T | <Step>Error``. ``retryable=True`` marks a
transport/runner flake the future pipeline may retry; ``False`` is a
business outcome (bad checkout, unparseable agent output, terminal
GitHub 4xx). Steps raise only on programmer error (empty ids).
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class V3StepError(BaseModel):
    """Base error value for every v3 step."""

    model_config = ConfigDict(frozen=True)

    message: str
    retryable: bool = False


class SandboxStepError(V3StepError):
    """Sandbox create/reconnect failed. Always retryable."""

    retryable: bool = True


class DbStateError(V3StepError):
    """The single-transaction db write failed. Always retryable."""

    retryable: bool = True


class CloneError(V3StepError):
    """Clone / fetch / checkout / verify failed."""


class IndexError(V3StepError):
    """Codegraph install / index failed."""


class DiffError(V3StepError):
    """Diff dir prep / ``git diff`` failed."""


class SplitError(V3StepError):
    """Split run failed or its summary is unparseable."""


class PlannerError(V3StepError):
    """Planner pi run failed or ``plan.jsonl`` is missing/invalid."""


class ReviewerError(V3StepError):
    """Review/summary pi run failed or its output is invalid."""


class PostError(V3StepError):
    """GitHub post failed transiently (429 / 5xx)."""


__all__ = [
    "CloneError",
    "DbStateError",
    "DiffError",
    "IndexError",
    "PlannerError",
    "PostError",
    "ReviewerError",
    "SandboxStepError",
    "SplitError",
    "V3StepError",
]
