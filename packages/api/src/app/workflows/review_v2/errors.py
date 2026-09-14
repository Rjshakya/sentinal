"""Typed errors for the v2 review workflow.

Same two-layer contract as :mod:`app.workflows.review.errors`:

**Error values** (subclasses of :class:`ReviewStepError`) — plain
Pydantic models *returned* (never raised) by the pure step functions.
Each carries a ``retryable`` flag plus the branded run identity so
the DBOS step edge can decide what to do without re-reading anything.

**Raised step exceptions** are reused from the v1 package
(:class:`ReviewStepFailure` / :class:`TransientReviewStepFailure`)
together with the shared :func:`shouldRetry` predicate and the
:func:`isLlmRetryError` classifier — the retry semantics are
identical, so they are imported, not duplicated.

V2-specific values:

- :class:`ChunkListError` — the chunk inventory (``ls`` + header
  parse over ``splitted_diffs/``) failed. Transient: the sandbox
  reconnect or the runner dropped the command.
- :class:`PlannerStepError` — the planning agent (research) or the
  plan extractor failed. ``phase`` records which half. A research
  failure on transient LLM/sandbox causes is retryable; an
  extraction schema mismatch is a business outcome — the workflow
  degrades the planner to an empty :class:`PlannerContext` instead
  of failing the run.
- :class:`FileLaneError` — one per-file review agent failed.
  ``file`` names the failing file (paths, not a fixed lane enum —
  the fan-out is N-wide); ``retryable`` mirrors whether the
  underlying failure was transient so the step edge can retry that
  file alone.
- :class:`V2AgentsError` — no usable agent output at all (planner
  degraded AND every file lane failed, or the file fan-out was
  empty-handed). Raised by the workflow body (wrapped in
  :class:`ReviewStepFailure`) after each lane exhausted its own step
  retries.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from app.workflows.review.errors import ReviewStepError


class ChunkListError(ReviewStepError):
    """The ``splitted_diffs/`` inventory could not be listed or parsed.

    Transient: sandbox reconnect / runner dropout — DBOS retries.
    """

    retryable: bool = True


class PlannerStepError(ReviewStepError):
    """The planning agent or the plan extractor failed.

    ``phase`` is ``"research"`` for the planning-agent run and
    ``"extract"`` for the structured-output transcription.
    ``retryable=True`` means a transient LLM / sandbox failure the
    step edge retries; ``False`` is a business outcome (empty output,
    schema mismatch) the workflow degrades to an empty planner
    context.
    """

    phase: Literal["research", "extract"] = "research"


class FileLaneError(ReviewStepError):
    """One per-file review agent (research) failed.

    ``file`` is the real repo path under review. ``retryable``
    mirrors whether the underlying failure was transient (LLM 429 /
    5xx / timeout, sandbox blip) so the step edge can retry that file
    alone.
    """

    file: str


class V2AgentsError(ReviewStepError):
    """No usable agent output for the run.

    Raised by the workflow body after every lane exhausted its own
    step retries: the planner degraded (or was skipped) and every
    file lane failed. Carries the per-file failures and the files
    that succeeded (empty here by construction, kept for shape
    parity with :class:`ReviewAgentsError`).
    """

    failedFiles: list[FileLaneError]
    succeededFiles: list[str]
    plannerDegraded: bool = True


__all__ = [
    "ChunkListError",
    "FileLaneError",
    "PlannerStepError",
    "V2AgentsError",
]
