"""Factory: pick a concrete sandbox adapter from a :class:`SandboxSpec`.

The factory is the only place that imports the concrete adapters. Callers
use the abstract :class:`BaseSandbox` interface, never the adapter classes
directly.
"""

from __future__ import annotations

from typing import Literal, overload

from app.core.config import settings
from app.core.sandbox.base import BaseSandbox
from app.core.sandbox.daytona import DaytonaSandbox, DaytonaSandboxSpec, get_daytona
from app.core.sandbox.e2b import E2BSandbox, E2BSandboxSpec
from app.core.sandbox.types import SandboxSpec


@overload
def create_sandbox(
    *, spec: E2BSandboxSpec, user_id: str, repo_id: str, sandbox_name: str
) -> E2BSandbox: ...


@overload
def create_sandbox(
    *, spec: DaytonaSandboxSpec, user_id: str, repo_id: str, sandbox_name: str
) -> DaytonaSandbox: ...


def create_sandbox(
    *,
    spec: SandboxSpec,
    user_id: str,
    repo_id: str,
    sandbox_name: str,
) -> BaseSandbox:
    """Construct (but do not create) a sandbox adapter for ``spec.provider``.

    Callers must still :meth:`BaseSandbox.create` to materialise the
    underlying VM/sandbox. This two-step pattern lets the caller register
    lifecycle hooks before the sandbox exists, and persist the resulting
    ``SandboxModel`` via those hooks.
    """
    if spec.provider == "e2b":
        return E2BSandbox(
            spec=spec,
            user_id=user_id,
            repo_id=repo_id,
            sandbox_name=sandbox_name,
        )

    if spec.provider == "daytona":
        return DaytonaSandbox(
            spec=spec,
            daytona_client=get_daytona(),
            user_id=user_id,
            repo_id=repo_id,
            sandbox_name=sandbox_name,
        )

    raise ValueError(
        f"Unknown sandbox provider: {spec.provider!r}. "
        "Expected one of: 'e2b', 'daytona'."
    )


@overload
def build_default_spec(provider: Literal["e2b"]) -> E2BSandboxSpec: ...


@overload
def build_default_spec(provider: Literal["daytona"]) -> DaytonaSandboxSpec: ...


def build_default_spec(provider: Literal["e2b", "daytona"]) -> SandboxSpec:
    """Build a :class:`SandboxSpec` from the current :class:`Settings`.

    The active provider is :attr:`Settings.sandbox_provider` (default
    ``"e2b"``). Provider-specific values are pulled from the corresponding
    ``e2b_*`` / ``daytona_*`` settings.

    Raises:
        RuntimeError: when the active provider's API key is missing.
        ValueError: when :attr:`Settings.sandbox_provider` is unknown.
    """

    if provider == "e2b":
        if not settings.e2b_api_key:
            raise RuntimeError(
                "E2B_API_KEY is not set. Add it to .env or set the "
                "E2B_API_KEY environment variable."
            )
        return SandboxSpec(
            provider="e2b",
            api_key=settings.e2b_api_key,
            template=settings.e2b_template or "code-interpreter-v1",
            cpu_count=settings.e2b_cpu_count,
            memory_mb=settings.e2b_memory_mb,
            timeout_s=settings.e2b_timeout_s,
        )

    if provider == "daytona":
        if not settings.daytona_api_key:
            raise RuntimeError(
                "DAYTONA_API_KEY is not set. Add it to .env or set the "
                "DAYTONA_API_KEY environment variable."
            )
        return SandboxSpec(
            provider="daytona",
            api_key=settings.daytona_api_key,
            template=settings.daytona_template or None,
        )

    raise ValueError(
        f"Unknown sandbox provider: {provider!r}. Expected one of: 'e2b', 'daytona'."
    )
