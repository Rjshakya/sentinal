"""Create the per-review ephemeral sandbox.

The review pipeline is **stateless**: every run creates its own fresh
sandbox, clones the repo into it, and destroys it in the workflow's
``finally`` (:func:`app.workflows.review.steps.kill_sandbox.killSandboxStep`).
No dependency on the setup-time per-repo ``sandboxes`` row.

Two layers:

- :func:`createSandbox` — the **pure** helper. Runs the provider's
  ``create()`` against the :class:`SandboxCtx`, returns the updated
  ctx (with ``sandboxId`` filled) or a :class:`SandboxCreateError`
  value.
- :func:`createSandboxStep` — the **DBOS step edge**. Logs and raises
  :class:`TransientReviewStepFailure` on failure so DBOS retries with a
  fresh sandbox.
"""

from __future__ import annotations

import logging

from dbos import DBOS

from app.services.sandbox.errors import SandboxProviderError
from app.services.sandbox.service import getProvider
from app.services.sandbox.types import SandboxCtx
from app.workflows.review.errors import (
    SandboxCreateError,
    TransientReviewStepFailure,
    shouldRetry,
)

log = logging.getLogger(__name__)


async def createSandbox(sandboxCtx: SandboxCtx) -> SandboxCtx | SandboxCreateError:
    """Create (or connect) the run's sandbox through the provider.

    The provider writes the provider-assigned id onto ``sandboxCtx``,
    so the returned ctx is the workflow's handle for every later step.
    """
    provider = getProvider(sandboxCtx.providerId)
    sandbox = await provider(ctx=sandboxCtx).create()
    if isinstance(sandbox, SandboxProviderError):
        return SandboxCreateError(
            message=sandbox.message,
            userId=sandbox.userId,
            repoId=sandbox.repoId,
        )
    return sandboxCtx


@DBOS.step(
    retries_allowed=True,
    max_attempts=3,
    should_retry=shouldRetry,
    backoff_rate=2,
)
async def createSandboxStep(sandboxCtx: SandboxCtx) -> SandboxCtx:
    """Durable step: create a fresh ephemeral sandbox for this run.

    Returns the updated :class:`SandboxCtx` (with ``sandboxId`` set)
    so only the id travels onward; every later step reconnects by it.

    Raises:
        TransientReviewStepFailure: E2B creation failed. DBOS retries
            the step, which creates a fresh sandbox.
    """
    result = await createSandbox(sandboxCtx)
    if isinstance(result, SandboxCreateError):
        log.warning(
            "create_sandbox_step: provider create failed (will retry): "
            "user_id=%s repo_id=%s provider=%s cause=%s",
            sandboxCtx.userId,
            sandboxCtx.repoId,
            sandboxCtx.providerId,
            result.message,
        )
        raise TransientReviewStepFailure(result)
    log.info(
        "create_sandbox_step: ok user_id=%s repo_id=%s sandbox_id=%s",
        sandboxCtx.userId,
        sandboxCtx.repoId,
        sandboxCtx.sandboxId,
    )
    return result


__all__ = ["createSandbox", "createSandboxStep"]