"""Provider-agnostic sandbox interface.

Every concrete adapter (``E2BSandbox``, ``DaytonaSandbox``, …) implements
this ABC. The rest of the app only ever talks to :class:`BaseSandbox`, so
swapping providers is a factory change, not a refactor of the callers.

Identity, lifecycle, and persistence are kept separate:

- Identity (``user_id``, ``repo_id``, ``sandbox_name``, ``spec``) is
  set at construction and treated as immutable.
- The lifecycle methods (``create``, ``stop``, ``kill``) call the
  provider, build a :class:`SandboxModel` for the registered hook to
  persist, and fire the hook.
- Persistence is the caller's concern — the registered hook
  (``on_create`` / ``on_pause`` / ``on_kill``) receives the model and
  decides what to do with it (insert / merge / log / notify).
"""

from __future__ import annotations

import inspect
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from app.core.sandbox.types import (
    CommandResult,
    CreateInfo,
    DeleteInfo,
    EntryInfo,
    SandboxInfo,
    SandboxSpec,
    WriteInfo,
)
from app.models.sandbox import Sandbox as SandboxModel

StreamCallback = Callable[[str], None] | Callable[[str], Awaitable[None]]
Hook = Callable[[SandboxModel], None] | Callable[[SandboxModel], Awaitable[None]]


class SandboxLifecycleError(RuntimeError):
    """Raised when a lifecycle operation is invalid for the current state."""


class SandboxAlreadyActive(Exception):
    """Raised when an active sandbox already exists for the (user, repo) pair."""

    def __init__(self, existing_sandbox_id: str) -> None:
        self.existing_sandbox_id = existing_sandbox_id
        super().__init__(f"Sandbox {existing_sandbox_id} is already active")


class BaseSandbox(ABC):
    """Abstract base class for all sandbox providers."""

    def __init__(
        self,
        *,
        spec: SandboxSpec,
        user_id: str,
        repo_id: str,
        sandbox_name: str,
    ) -> None:
        self._spec = spec
        self.user_id = user_id
        self.repo_id = repo_id
        self.sandbox_name = sandbox_name
        self._on_create_hook: Hook | None = None
        self._on_pause_hook: Hook | None = None
        self._on_kill_hook: Hook | None = None

    # ------------------------------------------------------------------ #
    # hooks (setters; the lifecycle methods fire them)                   #
    # ------------------------------------------------------------------ #

    def on_create(self, hook: Hook) -> None:
        """Register a callback fired after the underlying sandbox is created."""
        self._on_create_hook = hook

    def on_pause(self, hook: Hook) -> None:
        """Register a callback fired after the underlying sandbox is paused."""
        self._on_pause_hook = hook

    def on_kill(self, hook: Hook) -> None:
        """Register a callback fired after the underlying sandbox is killed."""
        self._on_kill_hook = hook

    # ------------------------------------------------------------------ #
    # lifecycle (abstract — each adapter implements the full flow)       #
    # ------------------------------------------------------------------ #

    @abstractmethod
    async def create(self) -> SandboxModel:
        """Create the underlying sandbox, build the model, fire on_create."""

    @abstractmethod
    async def stop(self) -> SandboxModel:
        """Pause the underlying sandbox, build the model, fire on_pause."""

    @abstractmethod
    async def kill(self) -> SandboxModel:
        """Kill the underlying sandbox, build the model, fire on_kill."""

    # ------------------------------------------------------------------ #
    # identity                                                           #
    # ------------------------------------------------------------------ #

    @property
    @abstractmethod
    def id(self) -> str:
        """Provider-assigned sandbox identifier. Empty before :meth:`create`."""

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Lower-case provider tag (``"e2b"`` / ``"daytona"``)."""

    @abstractmethod
    async def info(self) -> SandboxInfo:
        """Fetch live metadata for the sandbox."""

    # ------------------------------------------------------------------ #
    # command execution                                                  #
    # ------------------------------------------------------------------ #

    @abstractmethod
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
        """Run a shell command. Streaming callbacks (sync or async) are
        invoked for each chunk of stdout / stderr as it arrives."""

    # ------------------------------------------------------------------ #
    # filesystem                                                         #
    # ------------------------------------------------------------------ #

    @abstractmethod
    async def fs_write(
        self,
        path: str,
        data: bytes | str,
    ) -> WriteInfo:
        """Write ``data`` to ``path``. Auto-creates parent directories."""

    @abstractmethod
    async def fs_read(self, path: str) -> bytes:
        """Read raw bytes from ``path``. Raises if missing."""

    @abstractmethod
    async def fs_delete(self, path: str) -> DeleteInfo:
        """Delete ``path`` (file or directory)."""

    @abstractmethod
    async def fs_create_folder(self, path: str) -> CreateInfo:
        """Create a directory at ``path`` (recursive)."""

    @abstractmethod
    async def fs_list(self, path: str) -> list[EntryInfo]:
        """List entries directly under ``path``."""

    # ------------------------------------------------------------------ #
    # git                                                                #
    # ------------------------------------------------------------------ #

    @abstractmethod
    async def git_clone(
        self,
        url: str,
        dest: str,
        *,
        depth: int = 1,
    ) -> Any:
        """Clone ``url`` into ``dest`` (shallow by default)."""

    # ------------------------------------------------------------------ #
    # convenience shims                                                  #
    # ------------------------------------------------------------------ #

    async def upload_file(self, local_path: str | Path, remote_path: str) -> WriteInfo:
        """Read a local file and write it to the sandbox."""
        data = Path(local_path).read_bytes()
        return await self.fs_write(remote_path, data)

    async def upload_bytes(self, content: bytes, remote_path: str) -> WriteInfo:
        """Write raw bytes to the sandbox."""
        return await self.fs_write(remote_path, content)

    async def download_file(self, remote_path: str) -> bytes:
        """Alias for :meth:`fs_read` — kept for readability at call sites."""
        return await self.fs_read(remote_path)

    async def read_text(self, remote_path: str) -> str:
        """Read the file at ``remote_path`` and decode as UTF-8."""
        raw = await self.fs_read(remote_path)
        return raw.decode("utf-8", errors="ignore")

    async def execute_streaming(
        self,
        command: str,
        *,
        on_stdout: StreamCallback,
        on_stderr: StreamCallback | None = None,
        cwd: str | None = None,
        envs: dict[str, str] | None = None,
        timeout: float | None = None,
    ) -> CommandResult:
        """Sugar for :meth:`execute` with the streaming callbacks filled in."""
        return await self.execute(
            command,
            cwd=cwd,
            envs=envs,
            timeout=timeout,
            on_stdout=on_stdout,
            on_stderr=on_stderr,
        )

    # ------------------------------------------------------------------ #
    # internal helpers                                                   #
    # ------------------------------------------------------------------ #

    @staticmethod
    async def _maybe_await(callback: StreamCallback | None, chunk: str) -> None:
        """Invoke a streaming callback that may be sync or async."""
        if callback is None:
            return
        result = callback(chunk)
        if inspect.isawaitable(result):
            await result

    def _require_sandbox(self) -> None:
        """Subclasses call this before touching the underlying handle."""
        if getattr(self, "_sandbox", None) is None:
            raise SandboxLifecycleError(
                "Sandbox has not been created. Call create() first."
            )
