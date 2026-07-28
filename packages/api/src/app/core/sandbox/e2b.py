"""E2B adapter for the :class:`BaseSandbox` interface.

E2B maps cleanly onto every abstract method:

- lifecycle: ``create`` → ``AsyncSandbox.create``; ``stop`` → ``beta_pause``;
  ``kill`` → ``kill``.
- files: ``E2BSandbox.files.write/read/make_dir/remove/list``.
- command: ``E2BSandbox.commands.run`` with optional ``on_stdout`` /
  ``on_stderr`` callbacks (sync or async — the SDK accepts both).
- git: ``E2BSandbox.git.clone`` — native, supports ``depth``.
"""

from __future__ import annotations

import inspect
import logging
from datetime import UTC, datetime
from typing import Literal

from e2b import AsyncSandbox, LogEntry, Template
from e2b.sandbox.filesystem.filesystem import EntryInfo as E2BEntryInfo
from e2b.sandbox.filesystem.filesystem import FileType
from e2b.sandbox.filesystem.filesystem import WriteInfo as E2BWriteInfo
from e2b.sandbox.sandbox_api import SandboxLifecycle
from e2b.sandbox_async.commands.command import Commands as AsyncCommands
from e2b.sandbox_async.filesystem.filesystem import Filesystem as AsyncFilesystem
from e2b.sandbox_async.git import Git as AsyncGit

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

CODE_SANDBOX_TEMPLATE_NAME = "SENTINAL_CODE_SANDBOX_TEMP"
CODE_SANDBOX_CPU = 2
CODE_SANDBOX_MEM_IN_MB = 1024 * 2


def base_e2b_template():
    template = (
        Template()
        .from_python_image()
        .set_user("root")
        .run_cmd("mkdir -p /conversation_history")
    )
    return template


def log_e2b_template_build(data: LogEntry):
    log.info(data.message)


def build_e2b_template():
    build_info = Template.build(
        base_e2b_template(),
        CODE_SANDBOX_TEMPLATE_NAME,
        cpu_count=CODE_SANDBOX_CPU,
        memory_mb=CODE_SANDBOX_MEM_IN_MB,
        api_key=settings.e2b_api_key,
        on_build_logs=log_e2b_template_build,
    )
    return build_info


class E2BSandboxSpec(SandboxSpec):
    provider: Literal["e2b"] = "e2b"


class E2BSandbox(BaseSandbox):
    """E2B-backed :class:`BaseSandbox`."""

    def __init__(
        self,
        *,
        spec: SandboxSpec,
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
        self._sandbox: AsyncSandbox | None = None

    # ------------------------------------------------------------------ #
    # identity                                                           #
    # ------------------------------------------------------------------ #

    @property
    def provider_name(self) -> str:
        return "e2b"

    @property
    def id(self) -> str:
        if self._sandbox is None:
            return ""
        return self._sandbox.sandbox_id

    async def info(self) -> SandboxInfo:
        self._require_sandbox()
        assert self._sandbox is not None
        raw = await self._sandbox.get_info()
        return SandboxInfo(
            sandbox_id=raw.sandbox_id,
            state=str(raw.state.value)
            if hasattr(raw.state, "value")
            else str(raw.state),
            started_at=raw.started_at,
            timeout_s=self._spec.timeout_s,
            extra={
                "template_id": raw.template_id,
                "cpu_count": raw.cpu_count,
                "memory_mb": raw.memory_mb,
            },
        )

    # ------------------------------------------------------------------ #
    # internal accessors                                                 #
    # ------------------------------------------------------------------ #

    @property
    def sandbox(self) -> AsyncSandbox:
        """Underlying E2B sandbox; raises if :meth:`create` hasn't run."""
        self._require_sandbox()
        assert self._sandbox is not None
        return self._sandbox

    @property
    def files(self) -> AsyncFilesystem:
        return self.sandbox.files

    @property
    def commands(self) -> AsyncCommands:
        return self.sandbox.commands

    @property
    def git(self) -> AsyncGit:
        return self.sandbox.git

    # ------------------------------------------------------------------ #
    # lifecycle                                                          #
    # ------------------------------------------------------------------ #

    async def create(self) -> SandboxModel:

        log.info(
            "creating e2b sandbox: cpu=%d memory_mb=%d timeout_s=%d",
            self._spec.cpu_count,
            self._spec.memory_mb,
            self._spec.timeout_s,
        )

        # Resolve the template name from the spec. The default is the
        # E2B-hosted ``code-interpreter-v1`` template, which requires
        # no build. Custom templates can be configured via
        # ``E2B_TEMPLATE`` in the environment.

        self._sandbox = await AsyncSandbox.create(
            template=CODE_SANDBOX_TEMPLATE_NAME,
            api_key=settings.e2b_api_key,
            timeout=20 * 60,
            lifecycle=SandboxLifecycle(on_timeout="pause", auto_resume=True),
            metadata={
                "name": self.sandbox_name,
                "repo_id": self.repo_id,
                "user_id": self.user_id,
            },
        )

        log.info("e2b sandbox created: id=%s", self._sandbox.sandbox_id)

        model = SandboxModel(
            id=self.id,
            user_id=self.user_id,
            repo_id=self.repo_id,
            sandbox_name=self.sandbox_name,
            provider_id=self.provider_name,
            state=SandboxState.STARTED,
            started_at=datetime.now(UTC),
        )

        if self._on_create_hook is not None:
            result = self._on_create_hook(model)
            if inspect.isawaitable(result):
                await result
        return model

    async def stop(self) -> SandboxModel:
        if self._sandbox is not None:
            await self._sandbox.pause()
            model = SandboxModel(
                id=self.id,
                user_id=self.user_id,
                repo_id=self.repo_id,
                sandbox_name=self.sandbox_name,
                provider_id=self.provider_name,
                state=SandboxState.PAUSED,
            )
        else:
            model = SandboxModel(
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
            model = SandboxModel(
                id="",
                user_id=self.user_id,
                repo_id=self.repo_id,
                sandbox_name=self.sandbox_name,
                provider_id=self.provider_name,
                state=SandboxState.DELETED,
            )
            if self._on_kill_hook is not None:
                result = self._on_kill_hook(model)
                if inspect.isawaitable(result):
                    await result
            return model
        try:
            await self._sandbox.kill()
            log.info("e2b sandbox killed: id=%s", self._sandbox.sandbox_id)
        except Exception:
            log.exception(
                "e2b kill failed (id=%s); continuing",
                self._sandbox.sandbox_id,
            )

        model = SandboxModel(
            id=self.id,
            user_id=self.user_id,
            repo_id=self.repo_id,
            sandbox_name=self.sandbox_name,
            provider_id=self.provider_name,
            state=SandboxState.DELETED,
        )
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

        async def _stdout(chunk: str) -> None:
            await self._maybe_await(on_stdout, chunk)

        async def _stderr(chunk: str) -> None:
            await self._maybe_await(on_stderr, chunk)

        try:
            result = await self.commands.run(
                command,
                cwd=cwd,
                envs=envs,
                timeout=timeout if timeout is not None else 200,
                on_stdout=_stdout if on_stdout is not None else None,
                on_stderr=_stderr if on_stderr is not None else None,
            )
            return CommandResult(
                exit_code=result.exit_code,
                stdout=result.stdout or "",
                stderr=result.stderr or "",
                error=result.error,
            )
        except Exception as exc:
            return CommandResult(
                exit_code=-1,
                stdout="",
                stderr="",
                error=f"{type(exc).__name__}: {exc}",
            )

    @classmethod
    async def connect(
        cls,
        *,
        sandbox_id: str,
        sandbox_name: str,
        repo_id: str,
        user_id: str,
        spec: E2BSandboxSpec,
        timeout: int,
        api_key: str,
    ) -> E2BSandbox:

        sb = cls(spec=spec, user_id=user_id, repo_id=repo_id, sandbox_name=sandbox_name)
        sb._sandbox = await AsyncSandbox.connect(
            sandbox_id=sandbox_id, timeout=timeout, api_key=api_key
        )
        return sb

    # ------------------------------------------------------------------ #
    # filesystem                                                         #
    # ------------------------------------------------------------------ #

    async def fs_write(self, path: str, data: bytes | str) -> WriteInfo:
        self._require_sandbox()
        info: E2BWriteInfo = await self.files.write(path, data)
        return WriteInfo(path=info.path, success=True)

    async def fs_read(self, path: str) -> bytes:
        self._require_sandbox()
        return bytes(await self.files.read(path, format="bytes"))

    async def fs_delete(self, path: str) -> DeleteInfo:
        self._require_sandbox()
        try:
            await self.files.remove(path)
            return DeleteInfo(path=path, success=True)
        except Exception:
            log.exception("e2b fs_delete failed: path=%s", path)
            return DeleteInfo(path=path, success=False)

    async def fs_create_folder(self, path: str) -> CreateInfo:
        self._require_sandbox()
        ok = await self.files.make_dir(path)
        return CreateInfo(path=path, success=bool(ok))

    async def fs_list(self, path: str) -> list[EntryInfo]:
        self._require_sandbox()
        raw: list[E2BEntryInfo] = await self.files.list(path)
        return [
            EntryInfo(
                name=e.name,
                path=e.path,
                is_dir=(e.type == FileType.DIR),
                size=e.size,
            )
            for e in raw
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
    ):
        self._require_sandbox()
        result = await self.git.clone(url, path=dest, depth=depth)
        return result.exit_code
