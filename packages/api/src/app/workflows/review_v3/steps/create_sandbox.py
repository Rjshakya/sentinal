"""Create the per-run ephemeral sandbox.

One fresh sandbox per review run; every later step reconnects by the
returned ctx's ``sandboxId``. Provider create with a set ``sandboxId``
reconnects, so this same path serves create and reconnect.
"""

from __future__ import annotations

from app.services.sandbox.errors import SandboxProviderError
from app.services.sandbox.service import createSandboxCtx, getProvider
from app.services.sandbox.types import (
    BaseSandbox,
    ProviderId,
    SandboxCtx,
)
from app.utils.branded import RepoId, SanboxProviderApiKey, UserId
from app.workflows.review_v3.errors import SandboxStepError


async def createSandbox(
    *,
    userId: UserId,
    repoId: RepoId,
    repoName: str,
    providerId: ProviderId,
    apiKey: SanboxProviderApiKey,
    sandboxName: str,
    rootPath: str = "/home/user",
) -> SandboxCtx | SandboxStepError:
    """Create a fresh sandbox; return the ctx carrying its id."""
    if not repoName:
        raise ValueError("repoName must be non-empty")
    if not sandboxName:
        raise ValueError("sandboxName must be non-empty")
    if not rootPath:
        raise ValueError("rootPath must be non-empty")
    ctx = createSandboxCtx(
        userId=userId,
        repoId=repoId,
        repoName=repoName,
        providerId=providerId,
        apiKey=apiKey,
        sandboxName=sandboxName,
        rootPath=rootPath,
    )
    try:
        provider = getProvider(ctx.providerId)
    except Exception as exc:
        return SandboxStepError(
            message=f"unknown sandbox provider {ctx.providerId!r}: "
            f"{type(exc).__name__}: {exc}"
        )
    try:
        created: BaseSandbox | SandboxProviderError = await provider(ctx=ctx).create()
    except Exception as exc:
        return SandboxStepError(
            message=f"sandbox create raised {type(exc).__name__}: {exc}"
        )
    if isinstance(created, SandboxProviderError):
        return SandboxStepError(message=f"sandbox create failed: {created.message}")
    return ctx


__all__ = ["createSandbox"]
