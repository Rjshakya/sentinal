"""Internal helpers shared across the review pipeline.

Module-private (leading underscore on the file name) because nothing
outside the review package needs these:

- :data:`_SHOULD_RETRY_TRANSIENT` — the shared ``should_retry`` predicate
  used by every durable step that should retry on
  :class:`app.services.review.errors.TransientStepError` and fail on
  plain :class:`StepError` variants. Annotated as ``object`` because DBOS
  accepts any callable; we do not want a type checker to second-guess
  the exact signature.
- :data:`_SHOULD_RETRY_AGENT` — the ``should_retry`` predicate for the
  per-lane agent steps. Retries on any :class:`TransientStepError` and
  on any :class:`AgentInvocationError` /
  :class:`ReviewAgentsInvocationError` whose
  :attr:`AgentInvocationError.retryable` flag is ``True``.
- :func:`_e2b_spec` — reconstruct the active E2B spec from
  :class:`Settings`. Deterministic at workflow runtime because settings
  are loaded once on process startup and never change during a workflow.
"""

from __future__ import annotations

from typing import Literal, cast

from app.core.config import settings
from app.core.sandbox import build_default_spec
from app.core.sandbox.e2b import E2BSandboxSpec
from app.services.review.errors import (
    AgentInvocationError,
    ReviewAgentsInvocationError,
    TransientStepError,
)


def _should_retry_transient(exc: BaseException) -> bool:
    """Shared ``should_retry`` predicate for steps: retry on any
    :class:`TransientStepError`, fail on plain :class:`StepError`."""
    return isinstance(exc, TransientStepError)


def _should_retry_agent(exc: BaseException) -> bool:
    """``should_retry`` predicate for the per-lane agent steps.

    Retries on:

    - Any :class:`TransientStepError` (e.g. :class:`SandboxConnectError`).
    - A bare :class:`AgentInvocationError` with ``retryable=True`
      (raised by a single lane's step).

    The per-lane ``retryable`` flag is set by the
    ``invoke_<name>_agent`` wrappers based on :func:`is_llm_retry_error`.
    """
    if isinstance(exc, TransientStepError):
        return True
    if isinstance(exc, AgentInvocationError) and exc.retryable:
        return True
    if isinstance(exc, ReviewAgentsInvocationError) and any(
        e.retryable for e in exc.failed_agents
    ):
        return True
    return False


_SHOULD_RETRY_TRANSIENT = _should_retry_transient
"""Module-private alias used by ``@DBOS.step(should_retry=...)`` call sites."""

_SHOULD_RETRY_AGENT = _should_retry_agent
"""Module-private alias used by ``@DBOS.step(should_retry=...)`` call sites."""


def _e2b_spec() -> E2BSandboxSpec:
    """Reconstruct the active E2B spec from :class:`Settings`.

    Deterministic at workflow runtime because settings are loaded once
    on process startup and never change during a workflow. The cast
    narrows the abstract :class:`SandboxSpec` union to the concrete
    E2B variant.
    """
    provider: Literal["e2b", "daytona"] = (
        "daytona" if settings.sandbox_provider == "daytona" else "e2b"
    )
    return cast(E2BSandboxSpec, build_default_spec(provider))


__all__ = ["_SHOULD_RETRY_AGENT", "_SHOULD_RETRY_TRANSIENT", "_e2b_spec"]
