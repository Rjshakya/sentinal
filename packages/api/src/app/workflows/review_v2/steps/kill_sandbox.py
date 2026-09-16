"""DBOS durable step: best-effort sandbox kill.

The stateless review pipeline creates a fresh ephemeral sandbox per run
and the workflow's ``finally`` destroys it with this step, so no paused
sandboxes accumulate. Killing is idempotent on the provider side
(killing a dead sandbox is a no-op) and a failure here never masks the
run's outcome: the edge logs and returns.
"""

from __future__ import annotations

import logging
from typing import Protocol, cast

from dbos import DBOS

from app.services.sandbox.errors import SandboxProviderError
from app.services.sandbox.service import getProvider
from app.services.sandbox.types import SandboxCtx

log = logging.getLogger(__name__)


class _KillableProvider(Protocol):
    """The provider surface the kill step needs.

    ``BaseSandboxService`` declares create/connect only; the concrete
    providers additionally expose ``kill``, which this protocol names.
    """

    def __init__(self, ctx: SandboxCtx) -> None: ...

    async def kill(self) -> None | SandboxProviderError: ...


@DBOS.step()
async def killSandboxStep(
    *,
    sandboxCtx: SandboxCtx,
) -> None:
    """Durable step: destroy the ephemeral per-run sandbox.

    Best-effort cleanup: provider failures are logged, never raised.
    """
    ProviderCls = getProvider(sandboxCtx.providerId)
    provider = ProviderCls(ctx=sandboxCtx)
    result = await provider.kill()
    if isinstance(result, SandboxProviderError):
        log.warning(
            "kill_sandbox_step: failed to kill sandbox: sandbox_id=%s cause=%s",
            sandboxCtx.sandboxId,
            result.message,
        )
        return
    log.info(
        "kill_sandbox_step: ok sandbox_id=%s",
        sandboxCtx.sandboxId,
    )


__all__ = ["killSandboxStep"]
