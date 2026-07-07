"""Factory: pick a concrete sandbox adapter from a :class:`SandboxSpec`.

The factory is the only place that imports the concrete adapters. Callers
use the abstract :class:`BaseSandbox` interface, never the adapter classes
directly.
"""

from __future__ import annotations

from app.core.config import settings
from app.core.sandbox.base import BaseSandbox
from app.core.sandbox.daytona import DaytonaSandbox, get_daytona
from app.core.sandbox.e2b import E2BSandbox
from app.core.sandbox.types import SandboxSpec


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


def build_default_spec() -> SandboxSpec:
    """Build a :class:`SandboxSpec` from the current :class:`Settings`.

    The active provider is :attr:`Settings.sandbox_provider` (default
    ``"e2b"``). Provider-specific values are pulled from the corresponding
    ``e2b_*`` / ``daytona_*`` settings.

    Raises:
        RuntimeError: when the active provider's API key is missing.
        ValueError: when :attr:`Settings.sandbox_provider` is unknown.
    """

    provider = settings.sandbox_provider

    if provider == "e2b":
        if not settings.e2b_api_key:
            raise RuntimeError(
                "E2B_API_KEY is not set. Add it to .env or set the "
                "E2B_API_KEY environment variable."
            )
        return SandboxSpec(
            provider="e2b",
            api_key=settings.e2b_api_key,
            # template=settings.e2b_template,
            cpu_count=1,
            memory_mb=1026 * 6,
            # timeout_s=settings.e2b_timeout_s,
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
