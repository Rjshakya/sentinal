from typing import Literal

from deepagents.backends.sandbox import BaseSandbox
import e2b
from e2b.sandbox.sandbox_api import SandboxLifecycle
from langchain_e2b import AsyncE2BSandbox

from app.core.config import settings
from app.services.sandbox.errors import SandboxProviderError

from .types import BaseSandboxService, SandboxCtx, SandboxId

_E2B_CREATE_TIMEOUT_S: int = 20 * 60
"""Upper bound on the wall-clock duration of ``e2b.AsyncSandbox.create``."""

_E2B_CONNECT_TIMEOUT_S: int = 60 * 60
"""Upper bound on the wall-clock duration of ``e2b.AsyncSandbox.connect``."""


class E2BService(BaseSandboxService):
    def __init__(self, ctx: SandboxCtx):
        self.ctx: SandboxCtx = ctx
        self.sandbox: BaseSandbox | None = None

    async def create(self) -> BaseSandbox | SandboxProviderError:
        try:
            ctx = self.ctx
            if ctx.sandboxId is None:
                sandbox = await e2b.AsyncSandbox.create(
                    template=settings.e2b_template,
                    api_key=ctx.apiKey,
                    timeout=_E2B_CREATE_TIMEOUT_S,
                    lifecycle=SandboxLifecycle(on_timeout="pause", auto_resume=True),
                    metadata={
                        "name": ctx.sandboxName,
                        "repo_id": ctx.repoId,
                        "user_id": ctx.userId,
                    },
                )
                ctx.sandboxId = SandboxId(sandbox.sandbox_id)

            else:
                sandbox = await e2b.AsyncSandbox.connect(
                    sandbox_id=ctx.sandboxId,
                    timeout=_E2B_CONNECT_TIMEOUT_S,
                    api_key=ctx.apiKey,
                )

            self.ctx = ctx

            baseSanbox = AsyncE2BSandbox(sandbox=sandbox, workdir=ctx.rootPath)
            self.sandbox = baseSanbox
            return baseSanbox

        except Exception as exc:
            return SandboxProviderError(
                message="Failed to create sandbox",
                userId=self.ctx.userId,
                repoId=self.ctx.repoId,
                id="/services/sandbox/e2b",
                provider="e2b",
            )

    async def kill(self) -> None | SandboxProviderError:
        ctx = self.ctx
        if ctx.sandboxId is None:
            return
        try:
            await e2b.AsyncSandbox.kill(sandbox_id=ctx.sandboxId, api_key=ctx.apiKey)
            self.sandbox = None
        except Exception:
            return SandboxProviderError(
                message="Failed to kill sandbox",
                userId=self.ctx.userId,
                repoId=self.ctx.repoId,
                id="/services/sandbox/e2b",
                provider="e2b",
            )
