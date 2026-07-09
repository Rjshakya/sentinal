"""Daytona adapter for the :class:`BaseSandbox` interface.

Lifecycle mapping:
    - :meth:`create` → ``AsyncDaytona.create`` + ``wait_for_sandbox_start``
    - :meth:`stop`   → ``AsyncSandbox.stop``
    - :meth:`kill`   → ``AsyncSandbox.delete``

The active provider is E2B; this adapter is kept for the day we want to
swap back. ``build_sandbox_image`` is intentionally not exported from
the package — the pipeline never sees it.
"""

from __future__ import annotations

import inspect
import logging
import uuid
from datetime import UTC, datetime
from typing import Literal

from daytona import (
    AsyncDaytona,
    AsyncSandbox,
    CreateSandboxFromImageParams,
    DaytonaConfig,
    Image,
    Resources,
    SessionExecuteRequest,
)

from app.core.config import settings
from app.core.sandbox.base import BaseSandbox, StreamCallback
from app.core.sandbox.types import (
    CommandResult,
    CreateInfo,
    DeleteInfo,
    EntryInfo,
    SandboxInfo,
    SandboxSpec,
    WriteInfo,
)
from app.models.enums import SandboxState
from app.models.sandbox import Sandbox as SandboxModel

log = logging.getLogger(__name__)


class DaytonaSandboxSpec(SandboxSpec):
    provider: Literal["daytona"] = "daytona"


# --------------------------------------------------------------------------- #
# image builder (Daytona-specific; called by ``DaytonaSandbox.create``)        #
# --------------------------------------------------------------------------- #


def build_sandbox_image() -> Image:
    """Declarative Daytona image with ingestion deps baked in.

    Cached per runner for 24h; subsequent runs on the same runner reuse
    the built image and skip the ``pip install`` step.
    """
    return (
        Image.debian_slim("3.13")
        .pip_install(
            [
                "cognee",
                "tree-sitter-language-pack",
            ]
        )
        .run_commands(
            "apt-get update && "
            "apt-get install -y --no-install-recommends git curl && "
            "rm -rf /var/lib/apt/lists/*"
        )
        .workdir("/sentinel-workspace")
    )


def get_daytona():
    config = DaytonaConfig(api_key=settings.daytona_api_key)
    return AsyncDaytona(config)


# --------------------------------------------------------------------------- #
# adapter                                                                     #
# --------------------------------------------------------------------------- #


class DaytonaSandbox(BaseSandbox):
    """Daytona-backed :class:`BaseSandbox`.

    Lifecycle mapping:
        - :meth:`stop` → ``AsyncSandbox.stop``.
        - :meth:`kill` → ``AsyncSandbox.delete``.
    """

    def __init__(
        self,
        *,
        spec: SandboxSpec,
        daytona_client: AsyncDaytona,
        user_id: str,
        repo_id: str,
        sandbox_name: str,
    ) -> None:
        super().__init__(
            spec=spec,
            user_id=user_id,
            repo_id=repo_id,
            sandbox_name=sandbox_name,
        )
        self._daytona: AsyncDaytona = daytona_client
        self._sandbox: AsyncSandbox | None = None

    # ------------------------------------------------------------------ #
    # identity                                                           #
    # ------------------------------------------------------------------ #

    @property
    def provider_name(self) -> str:
        return "daytona"

    @property
    def id(self) -> str:
        if self._sandbox is None:
            return ""
        return self._sandbox.id

    @property
    def sandbox(self) -> AsyncSandbox:
        """Underlying Daytona sandbox; raises if :meth:`create` hasn't run."""
        self._require_sandbox()
        assert self._sandbox is not None
        return self._sandbox

    async def info(self) -> SandboxInfo:
        self._require_sandbox()
        assert self._sandbox is not None
        raw = await self._daytona.get(self._sandbox.id)
        return SandboxInfo(
            sandbox_id=raw.id,
            state=str(raw.state) if hasattr(raw, "state") else "unknown",
            started_at=None,
            timeout_s=self._spec.timeout_s,
            extra={
                "name": getattr(raw, "name", None),
                "auto_stop_interval": getattr(raw, "auto_stop_interval", None),
            },
        )

    # ------------------------------------------------------------------ #
    # lifecycle                                                          #
    # ------------------------------------------------------------------ #

    async def create(self) -> SandboxModel:

        if not self._spec.template:
            raise ValueError(
                "DaytonaSandbox requires spec.template (the image name) to create a sandbox."
            )
        log.info(
            "creating daytona sandbox (image=%s, cpu=%d, mem=%dMB, timeout=%ds)",
            self._spec.template,
            self._spec.cpu_count,
            self._spec.memory_mb,
            self._spec.timeout_s,
        )
        params = CreateSandboxFromImageParams(
            name=self.sandbox_name,
            image=build_sandbox_image(),
            resources=Resources(
                cpu=self._spec.cpu_count,
                memory=self._spec.memory_mb,
                disk=int(self._spec.extra.get("disk_gb", 8)),
            ),
        )
        self._sandbox = await self._daytona.create(params)
        await self._sandbox.wait_for_sandbox_start()
        log.info("daytona sandbox created: id=%s", self._sandbox.id)

        model = await self.update_state(
            id=self.id,
            user_id=self.user_id,
            repo_id=self.repo_id,
            sandbox_name=self.sandbox_name,
            provider_id=self.provider_name,
            state=SandboxState.STARTED,
        )
        if self._on_create_hook is not None:
            result = self._on_create_hook(model)
            if inspect.isawaitable(result):
                await result
        return model

    async def stop(self) -> SandboxModel:
        self._require_sandbox()
        assert self._sandbox is not None
        try:
            await self._sandbox.stop()
            log.info("daytona sandbox stopped: id=%s", self._sandbox.id)
        except Exception:
            log.exception(
                "daytona stop failed (id=%s); continuing",
                self._sandbox.id,
            )

        model = await self.update_state(
            id=self.id,
            user_id=self.user_id,
            repo_id=self.repo_id,
            sandbox_name=self.sandbox_name,
            provider_id=self.provider_name,
            state=SandboxState.PAUSED,
        )
        model.stopped_at = datetime.now(UTC)
        if self._on_pause_hook is not None:
            result = self._on_pause_hook(model)
            if inspect.isawaitable(result):
                await result
        return model

    async def kill(self) -> SandboxModel:
        if self._sandbox is None:
            return await self.update_state(
                id="",
                user_id=self.user_id,
                repo_id=self.repo_id,
                sandbox_name=self.sandbox_name,
                provider_id=self.provider_name,
                state=SandboxState.DELETED,
            )
        try:
            await self._sandbox.delete()
            log.info("daytona sandbox deleted: id=%s", self._sandbox.id)
        except Exception:
            log.exception(
                "daytona delete failed (id=%s); continuing",
                self._sandbox.id,
            )

        model = await self.update_state(
            id=self.id,
            user_id=self.user_id,
            repo_id=self.repo_id,
            sandbox_name=self.sandbox_name,
            provider_id=self.provider_name,
            state=SandboxState.DELETED,
        )
        model.state = SandboxState.DELETED
        model.stopped_at = datetime.now(UTC)
        if self._on_kill_hook is not None:
            result = self._on_kill_hook(model)
            if inspect.isawaitable(result):
                await result
        return model

    # ------------------------------------------------------------------ #
    # command execution                                                  #
    # ------------------------------------------------------------------ #

    async def execute(
        self,
        command: str,
        *,
        cwd: str | None = None,
        envs: dict[str, str] | None = None,
        timeout: float | None = None,
        on_stdout: StreamCallback | None = None,
        on_stderr: StreamCallback | None = None,
    ) -> CommandResult:
        self._require_sandbox()
        sb = self.sandbox

        if on_stdout is None and on_stderr is None:
            response = await sb.process.exec(
                command,
                cwd=cwd,
                env=envs,
                timeout=int(timeout) if timeout is not None else None,
            )
            return CommandResult(
                exit_code=response.exit_code if response.exit_code is not None else 0,
                stdout=response.result or "",
                stderr="",
            )

        session_id = f"exec-{uuid.uuid4().hex[:8]}"
        await sb.process.create_session(session_id)
        try:
            cmd = await sb.process.execute_session_command(
                session_id,
                SessionExecuteRequest(command=command, run_async=True),
            )

            async def _on_stdout(chunk: str) -> None:
                await self._maybe_await(on_stdout, chunk)

            async def _on_stderr(chunk: str) -> None:
                await self._maybe_await(on_stderr, chunk)

            await sb.process.get_session_command_logs_async(
                session_id,
                cmd.cmd_id,
                _on_stdout,
                _on_stderr,
            )

            final_cmd = await sb.process.get_session_command(session_id, cmd.cmd_id)
            final_logs = await sb.process.get_session_command_logs(
                session_id, cmd.cmd_id
            )

            full_stdout = (final_logs.stdout or "") + (final_logs.stderr or "")
            return CommandResult(
                exit_code=final_cmd.exit_code if final_cmd.exit_code is not None else 0,
                stdout=full_stdout,
                stderr=final_logs.stderr or "",
            )
        finally:
            try:
                await sb.process.delete_session(session_id)
            except Exception:
                log.debug(
                    "daytona session delete failed (id=%s)", session_id, exc_info=True
                )

    # ------------------------------------------------------------------ #
    # filesystem                                                         #
    # ------------------------------------------------------------------ #

    async def fs_write(self, path: str, data: bytes | str) -> WriteInfo:
        self._require_sandbox()
        await self.sandbox.fs.upload_file(data, path)
        return WriteInfo(path=path, success=True)

    async def fs_read(self, path: str) -> bytes:
        self._require_sandbox()
        raw = await self.sandbox.fs.download_file(path)
        if raw is None:
            raise FileNotFoundError(f"daytona fs_read: file not found at {path!r}")
        return raw

    async def fs_delete(self, path: str) -> DeleteInfo:
        self._require_sandbox()
        try:
            await self.sandbox.fs.delete_file(path, recursive=True)
            return DeleteInfo(path=path, success=True)
        except Exception:
            log.exception("daytona fs_delete failed: path=%s", path)
            return DeleteInfo(path=path, success=False)

    async def fs_create_folder(self, path: str) -> CreateInfo:
        self._require_sandbox()
        try:
            await self.sandbox.fs.create_folder(path, "755")
            return CreateInfo(path=path, success=True)
        except Exception:
            log.exception("daytona fs_create_folder failed: path=%s", path)
            return CreateInfo(path=path, success=False)

    async def fs_list(self, path: str) -> list[EntryInfo]:
        self._require_sandbox()
        raw = await self.sandbox.fs.list_files(path)
        return [
            EntryInfo(
                name=f.name,
                path=path.rstrip("/") + "/" + f.name,
                is_dir=bool(f.is_dir),
                size=f.size if not f.is_dir else None,
            )
            for f in raw
        ]

    # ------------------------------------------------------------------ #
    # git                                                                #
    # ------------------------------------------------------------------ #

    async def git_clone(
        self,
        url: str,
        dest: str,
        *,
        depth: int = 1,
    ) -> None:
        self._require_sandbox()
        depth_args = f"--depth {depth} " if depth and depth > 0 else ""
        await self.sandbox.process.exec(
            f"git clone {depth_args}{url} {dest}",
            timeout=300,
        )


__all__ = [
    "DaytonaSandbox",
    "build_sandbox_image",
]
