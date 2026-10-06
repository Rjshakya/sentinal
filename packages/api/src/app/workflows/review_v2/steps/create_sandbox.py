"""Create the per-review ephemeral sandbox.

The review pipeline is **stateless**: every run creates its own fresh
sandbox, clones the repo into it, and destroys it at the end of the
run. No dependency on the setup-time per-repo ``sandboxes`` row.
"""

from __future__ import annotations

import logging

from app.services.sandbox.errors import SandboxProviderError
from app.services.sandbox.service import getProvider
from app.services.sandbox.types import SandboxCtx
from app.workflows.review_v2.errors import (
    SandboxCreateError,
    TransientReviewStepFailure,
)

log = logging.getLogger(__name__)


async def createSandboxStep(sandboxCtx: SandboxCtx) -> SandboxCtx:
    """Create a fresh ephemeral sandbox for this run.

    Returns the updated :class:`SandboxCtx` (with ``sandboxId`` set)
    so only the id travels onward; every later step reconnects by it.

    Raises:
        TransientReviewStepFailure: provider creation failed.
    """
    provider = getProvider(sandboxCtx.providerId)
    sandbox = await provider(ctx=sandboxCtx).create()
    if isinstance(sandbox, SandboxProviderError):
        log.warning(
            "create_sandbox_step: provider create failed (will retry): "
            "user_id=%s repo_id=%s provider=%s cause=%s",
            sandboxCtx.userId,
            sandboxCtx.repoId,
            sandboxCtx.providerId,
            sandbox.message,
        )
        raise TransientReviewStepFailure(
            SandboxCreateError(
                message=sandbox.message,
                userId=sandbox.userId,
                repoId=sandbox.repoId,
            )
        )
    log.info(
        "create_sandbox_step: ok user_id=%s repo_id=%s sandbox_id=%s",
        sandboxCtx.userId,
        sandboxCtx.repoId,
        sandboxCtx.sandboxId,
    )
    return sandboxCtx


__all__ = ["createSandboxStep"]
