"""Docker provider: production-compatible lifecycle over one container.

Adapts the eval ``DockerService`` to the production
``BaseSandboxService`` contract. Containers live in a module-level
registry keyed by container id; ``kill`` removes the entry and the
container.
"""

from __future__ import annotations

from deepagents.backends.sandbox import BaseSandbox

from app.services.sandbox.errors import SandboxProviderError
from app.services.sandbox.types import BaseSandboxService, SandboxCtx, SandboxId
from environments.base import EnvConfig, EnvError
from environments.docker import DockerBackend, DockerService

_REGISTRY: dict[str, tuple[DockerBackend, DockerService]] = {}


def _provider_error(ctx: SandboxCtx, message: str) -> SandboxProviderError:
    return SandboxProviderError(
        message=message,
        userId=ctx.userId,
        repoId=ctx.repoId,
        id="/evals/providers/docker",
        provider="docker",
    )


class DockerProvider(BaseSandboxService):
    """Create / reconnect / destroy docker sandboxes for one ctx."""

    def __init__(self, ctx: SandboxCtx) -> None:
        self.ctx = ctx

    async def create(self) -> BaseSandbox | SandboxProviderError:
        sid = self.ctx.sandboxId
        if sid is not None and str(sid) in _REGISTRY:
            return _REGISTRY[str(sid)][0]
        svc = DockerService(EnvConfig(kind="docker"))
        backend = await svc.create()
        if isinstance(backend, EnvError):
            return _provider_error(self.ctx, backend.message)
        _REGISTRY[backend.id] = (backend, svc)
        self.ctx.sandboxId = SandboxId(backend.id)
        return backend

    async def connect(self) -> None | SandboxProviderError:
        sid = self.ctx.sandboxId
        if sid is None or str(sid) not in _REGISTRY:
            return _provider_error(self.ctx, "docker sandbox is not initialised")
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
            return _provider_error(self.ctx, result.message)
        return None


__all__ = ["DockerProvider"]
