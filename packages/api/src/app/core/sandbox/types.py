"""Shared dataclasses for the sandbox abstraction.

These types are provider-agnostic. Concrete adapters (E2B / Daytona) may
reuse the underlying provider's dataclasses when their shapes already
match — the goal here is only to define what the *interface* looks like.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class CommandResult:
    """Result of a sandbox command execution."""

    exit_code: int
    stdout: str = ""
    stderr: str = ""
    error: str | None = None


@dataclass(frozen=True)
class WriteInfo:
    """Outcome of a single file write."""

    path: str
    success: bool


@dataclass(frozen=True)
class DeleteInfo:
    """Outcome of a single file/directory delete."""

    path: str
    success: bool


@dataclass(frozen=True)
class CreateInfo:
    """Outcome of a directory creation."""

    path: str
    success: bool


@dataclass(frozen=True)
class EntryInfo:
    """A single filesystem entry as returned by :meth:`BaseSandbox.fs_list`."""

    name: str
    path: str
    is_dir: bool
    size: int | None = None


@dataclass(frozen=True)
class SandboxInfo:
    """Provider-agnostic metadata about a running sandbox."""

    sandbox_id: str
    state: str
    started_at: datetime | None = None
    timeout_s: int | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SandboxSpec:
    """Static configuration passed to a sandbox adapter at construction time.

    Carries everything an adapter needs to know up-front: which provider to
    talk to, the auth key, the template/image, and resource limits. No
    per-instance state — the adapter creates its underlying handle inside
    :meth:`BaseSandbox.create`.
    """

    provider: str
    api_key: str
    template: str | None = None
    cpu_count: int = 1
    memory_mb: int = 1024
    timeout_s: int = 600
    extra: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.provider not in {"e2b", "daytona"}:
            raise ValueError(
                f"Unknown sandbox provider: {self.provider!r}. "
                "Expected one of: 'e2b', 'daytona'."
            )
        if not self.api_key:
            raise ValueError(
                f"SandboxSpec for provider {self.provider!r} requires an api_key."
            )
