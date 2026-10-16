"""Local provider: production-compatible lifecycle over a temp dir.

Adapts the eval ``LocalService`` to the production
``BaseSandboxService`` contract so the review workers reconnect by id
through the shared provider map. Backends live in a module-level
registry keyed by sandbox id (mirroring the cloud providers'
server-side registry); ``kill`` removes the entry and its directory.
"""

from __future__ import annotations

from deepagents.backends.sandbox import BaseSandbox

from app.services.sandbox.errors import SandboxProviderError
from app.services.sandbox.types import BaseSandboxService, SandboxCtx, SandboxId
from environments.base import EnvConfig, EnvError
from environments.local import LocalBackend, LocalService

_REGISTRY: dict[str, tuple[LocalBackend, LocalService]] = {}


def buildProviderError(ctx: SandboxCtx, message: str) -> SandboxProviderError:
    return SandboxProviderError(
        message=message,
        userId=ctx.userId,
        repoId=ctx.repoId,
        id="/evals/providers/local",
        provider="local",
    )


class LocalProvider(BaseSandboxService):
    """Create / reconnect / destroy local sandboxes for one ctx."""

    def __init__(self, ctx: SandboxCtx) -> None:
        self.ctx = ctx

    async def create(self) -> BaseSandbox | SandboxProviderError:
        sid = self.ctx.sandboxId
        if sid is not None and str(sid) in _REGISTRY:
            return _REGISTRY[str(sid)][0]
        svc = LocalService(EnvConfig(kind="local"))
        backend = await svc.create()
        if isinstance(backend, EnvError):
            return buildProviderError(self.ctx, backend.message)
        _REGISTRY[backend.id] = (backend, svc)
        self.ctx.sandboxId = SandboxId(backend.id)
        root = svc.sandbox_root
        if root is not None:
            self.ctx.rootPath = root
        return backend

    async def connect(self) -> None | SandboxProviderError:
        sid = self.ctx.sandboxId
        if sid is None or str(sid) not in _REGISTRY:
            return buildProviderError(self.ctx, "local sandbox is not initialised")
        return None

    async def kill(self) -> None | SandboxProviderError:
        sid = self.ctx.sandboxId
        if sid is None:
            return None
        entry = _REGISTRY.pop(str(sid), None)
        if entry is None:
            return None
        _, svc = entry
        result = await svc.kill()
        if isinstance(result, EnvError):
            return buildProviderError(self.ctx, result.message)
        return None


__all__ = ["LocalProvider"]
