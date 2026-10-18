"""E2B environment: cloud sandboxes behind the eval service boundary.

Reuses the production lifecycle (``e2b.AsyncSandbox`` plus the
LangChain ``AsyncE2BSandbox`` backend) so eval runs see the same
filesystem the review pipeline sees. Only ``create`` / ``connect`` /
``kill`` live here; command execution stays inside the backend.
"""

from __future__ import annotations

from deepagents.backends.sandbox import BaseSandbox

from environments.base import BaseSandboxService, EnvConfig, EnvError

_CREATE_TIMEOUT_S = 20 * 60
_CONNECT_TIMEOUT_S = 60 * 60


class E2BService(BaseSandboxService):
    """Create / reconnect / destroy E2B sandboxes for one eval run."""

    async def create(self) -> BaseSandbox | EnvError:
        try:
            import e2b
            from e2b.sandbox.sandbox_api import SandboxLifecycle
            from langchain_e2b import AsyncE2BSandbox
        except ImportError as exc:
            return EnvError(
                message=f"e2b packages not installed: {exc}",
                provider="e2b",
            )
        if not self.cfg.api_key:
            return EnvError(message="e2b api key is empty", provider="e2b")
        try:
            sandbox = await e2b.AsyncSandbox.create(
                template=self.cfg.template or None,
                api_key=self.cfg.api_key,
                timeout=_CREATE_TIMEOUT_S,
                lifecycle=SandboxLifecycle(on_timeout="pause", auto_resume=True),
                metadata={"name": "sentinel-eval"},
            )
            backend: BaseSandbox = AsyncE2BSandbox(
                sandbox=sandbox, workdir=self.cfg.root_path or "/home/user"
            )
            self._backend = backend
            return backend
        except Exception as exc:
            return EnvError(
                message=f"e2b create failed: {type(exc).__name__}: {exc}",
                provider="e2b",
            )

    async def connect(self, sandbox_id: str) -> BaseSandbox | EnvError:
        try:
            import e2b
            from langchain_e2b import AsyncE2BSandbox
        except ImportError as exc:
            return EnvError(
                message=f"e2b packages not installed: {exc}",
                provider="e2b",
            )
        if not self.cfg.api_key:
            return EnvError(message="e2b api key is empty", provider="e2b")
        try:
            sandbox = await e2b.AsyncSandbox.connect(
                sandbox_id=sandbox_id,
                timeout=_CONNECT_TIMEOUT_S,
                api_key=self.cfg.api_key,
            )
            backend: BaseSandbox = AsyncE2BSandbox(
                sandbox=sandbox, workdir=self.cfg.root_path or "/home/user"
            )
            self._backend = backend
            return backend
        except Exception as exc:
            return EnvError(
                message=f"e2b connect failed: {type(exc).__name__}: {exc}",
                provider="e2b",
            )

    async def kill(self) -> None | EnvError:
        backend = self._backend
        sandbox_id = backend.id if backend is not None else ""
        self._backend = None
        if not sandbox_id or sandbox_id.startswith("local-"):
            return None
        try:
            import e2b
        except ImportError:
            return None
        if not self.cfg.api_key:
            return None
        try:
            await e2b.AsyncSandbox.kill(
                sandbox_id=sandbox_id, api_key=self.cfg.api_key
            )
            return None
        except Exception as exc:
            return EnvError(
                message=f"e2b kill failed: {type(exc).__name__}: {exc}",
                provider="e2b",
            )


__all__ = ["E2BService"]
