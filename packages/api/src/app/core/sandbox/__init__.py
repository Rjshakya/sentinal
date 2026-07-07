"""Sandbox provider abstraction.

Every concrete sandbox provider (E2B, Daytona, …) is exposed through a
single :class:`BaseSandbox` interface so that the rest of the app stays
provider-agnostic. The :func:`create_sandbox` factory in ``factory.py``
dispatches to the configured provider based on :class:`SandboxSpec.provider`.
"""

from app.core.sandbox.base import (
    BaseSandbox,
    Hook,
    SandboxAlreadyActive,
    SandboxLifecycleError,
    StreamCallback,
)
from app.core.sandbox.factory import (
    SandboxSpec,
    build_default_spec,
    create_sandbox,
)
from app.core.sandbox.types import (
    CommandResult,
    CreateInfo,
    DeleteInfo,
    EntryInfo,
    SandboxInfo,
    WriteInfo,
)
from app.models.sandbox import Sandbox as SandboxModel

__all__ = [
    "BaseSandbox",
    "CommandResult",
    "CreateInfo",
    "DeleteInfo",
    "EntryInfo",
    "Hook",
    "SandboxInfo",
    "SandboxAlreadyActive",
    "SandboxLifecycleError",
    "SandboxModel",
    "SandboxSpec",
    "StreamCallback",
    "WriteInfo",
    "build_default_spec",
    "create_sandbox",
]
