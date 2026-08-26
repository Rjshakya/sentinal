"""Sandbox service: provider map over LangChain's sandbox backends.

Two entry points:

- :func:`createSandboxCtx` — assemble the serializable run context. Provider,
  api key, sandbox name, and root path all fall back to sensible defaults
  (settings-driven) so callers only pass what they actually know.
- :func:`createSandbox` — the provider map: build the LangChain sandbox
  backend (``deepagents.backends.sandbox.BaseSandbox``) for a ctx's
  ``providerId``. This is the **only** place providers are wired: each map
  entry delegates to LangChain's sandbox backend for that provider
  (``langchain_e2b``'s ``AsyncE2BSandbox``) plus the few lifecycle calls
  (create/connect/kill) the backend protocol does not cover, so no custom
  provider classes live in this repo. Callers talk to the ``BaseSandbox``
  interface, never a concrete provider class.

Credentials: :attr:`SandboxCtx.apiKey` is resolved from settings by
:func:`createSandboxCtx` (``E2B_API_KEY`` / ``DAYTONA_API_KEY``) and
passed to the provider SDK on every lifecycle call — the ctx stays the
single source of truth.

Lifecycle: ``BaseSandbox`` is a backend wrapper — it executes commands and
file operations against an already-running sandbox. Creation/connect and
teardown are owned by the provider map entries: :func:`createSandbox`
creates a fresh sandbox (or reconnects when the ctx carries a
``sandboxId``) and wraps it in the LangChain backend, and
:func:`killSandbox` destroys it. Pausing is not part of LangChain's
sandbox protocol and is intentionally absent.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import cast

import e2b
from deepagents.backends.sandbox import BaseSandbox
from e2b.sandbox.sandbox_api import SandboxLifecycle as E2BSandboxLifecycle
from langchain_e2b import AsyncE2BSandbox

from app.core.config import settings
from app.core.sandbox.e2b import CODE_SANDBOX_TEMPLATE_NAME
from app.services.sandbox.types import (
    ApiKey,
    ProviderId,
    RepoId,
    SandboxCtx,
    SandboxId,
    UserId,
)

log = logging.getLogger(__name__)

SandboxFactory = Callable[[SandboxCtx], Awaitable[BaseSandbox]]
"""Provider map entry: build a LangChain sandbox backend from a ctx."""

SandboxKiller = Callable[[SandboxCtx], Awaitable[None]]
"""Provider map entry: destroy the sandbox referenced by a ctx."""

_DEFAULT_ROOT_PATH: dict[ProviderId, str] = {
    "e2b": "/home/user",
    "daytona": "/sentinel-workspace",
}
"""Per-provider default working directory (matches each provider's image)."""

_E2B_CREATE_TIMEOUT_S: int = 20 * 60
"""Upper bound on the wall-clock duration of ``e2b.AsyncSandbox.create``."""

_E2B_CONNECT_TIMEOUT_S: int = 60 * 60
"""Upper bound on the wall-clock duration of ``e2b.AsyncSandbox.connect``."""


def _resolveProviderId(providerId: ProviderId | None) -> ProviderId:
    """Return ``providerId`` or the active provider from settings."""
    if providerId is not None:
        return providerId
    raw = settings.sandbox_provider
    if raw not in ("e2b", "daytona"):
        raise ValueError(f"Unknown sandbox provider from settings: {raw!r}")
    return cast(ProviderId, raw)


def _resolveApiKey(providerId: ProviderId, apiKey: ApiKey | None) -> ApiKey | None:
    """Return ``apiKey`` or the active provider's key from settings."""
    if apiKey is not None:
        return apiKey
    env_key = settings.e2b_api_key if providerId == "e2b" else settings.daytona_api_key
    return ApiKey(env_key) if env_key else None


def _resolveTemplate() -> str:
    """Return the active E2B template from settings.

    Empty / ``code-interpreter-v1`` (the Pydantic default) falls back to
    the locally-built :data:`CODE_SANDBOX_TEMPLATE_NAME`.
    """
    template = settings.e2b_template
    if not template or template == "code-interpreter-v1":
        return CODE_SANDBOX_TEMPLATE_NAME
    return template


def _requireApiKey(ctx: SandboxCtx) -> ApiKey:
    """Return the ctx's API key; raise when the provider key is unset."""
    if not ctx.apiKey:
        raise RuntimeError(
            f"{ctx.providerId} API key is missing (set the provider's env "
            "key or pass apiKey to createSandboxCtx)"
        )
    return ctx.apiKey


async def _createE2B(ctx: SandboxCtx) -> BaseSandbox:
    """Create/connect an E2B sandbox and wrap it in LangChain's backend.

    ``ctx.sandboxId`` set → reconnect to that sandbox; ``None`` → create a
    fresh one from the resolved template. When a sandbox is created, the
    provider id is written onto ``ctx.sandboxId`` so the ctx stays the
    single source of truth.
    """
    api_key = _requireApiKey(ctx)
    if ctx.sandboxId is None:
        sandbox = await e2b.AsyncSandbox.create(
            template=_resolveTemplate(),
            api_key=api_key,
            timeout=_E2B_CREATE_TIMEOUT_S,
            lifecycle=E2BSandboxLifecycle(on_timeout="pause", auto_resume=True),
            metadata={
                "name": ctx.sandboxName,
                "repo_id": ctx.repoId,
                "user_id": ctx.userId,
            },
        )
        ctx.sandboxId = SandboxId(sandbox.sandbox_id)
        log.info(
            "e2b sandbox created: id=%s name=%s repo_id=%s",
            ctx.sandboxId,
            ctx.sandboxName,
            ctx.repoId,
        )
    else:
        sandbox = await e2b.AsyncSandbox.connect(
            sandbox_id=ctx.sandboxId,
            timeout=_E2B_CONNECT_TIMEOUT_S,
            api_key=api_key,
        )
    return AsyncE2BSandbox(sandbox=sandbox, workdir=ctx.rootPath)


async def _killE2B(ctx: SandboxCtx) -> None:
    """Destroy the E2B sandbox referenced by ``ctx.sandboxId`` (best-effort)."""
    if ctx.sandboxId is None:
        return
    try:
        await e2b.AsyncSandbox.kill(
            sandbox_id=ctx.sandboxId, api_key=_requireApiKey(ctx)
        )
        log.info("e2b sandbox killed: id=%s", ctx.sandboxId)
    except Exception:
        log.warning(
            "e2b kill failed (best-effort): id=%s", ctx.sandboxId, exc_info=True
        )


_SANDBOX_PROVIDERS: dict[ProviderId, SandboxFactory] = {
    "e2b": _createE2B,
    # "daytona": TODO — wire langchain_daytona.DaytonaSandbox once the
    #   langchain-daytona dependency is added.
}
"""Provider map: the only place concrete providers are wired."""

_SANDBOX_KILLERS: dict[ProviderId, SandboxKiller] = {
    "e2b": _killE2B,
}
"""Kill map: destroy the sandbox referenced by a ctx's ``sandboxId``."""


def createSandboxCtx(
    *,
    userId: UserId,
    repoId: RepoId,
    repoName: str,
    providerId: ProviderId | None = None,
    apiKey: ApiKey | None = None,
    sandboxName: str | None = None,
    rootPath: str | None = None,
) -> SandboxCtx:
    """Assemble a :class:`SandboxCtx` with settings-driven defaults.

    Defaults:
    - ``providerId`` — :attr:`app.core.config.Settings.sandbox_provider`.
    - ``apiKey``     — the provider's env key (``E2B_API_KEY`` /
      ``DAYTONA_API_KEY``); ``None`` when unset. The map entries pass this
      key to the provider SDK on every lifecycle call.
    - ``sandboxName`` — ``"review-{repoName}"``.
    - ``rootPath``   — the provider's default workdir (``/home/user`` for
      e2b, ``/sentinel-workspace`` for daytona).
    """
    provider = _resolveProviderId(providerId)
    return SandboxCtx(
        userId=userId,
        repoId=repoId,
        repoName=repoName,
        providerId=provider,
        apiKey=_resolveApiKey(provider, apiKey),
        sandboxName=sandboxName or f"review-{repoName}",
        rootPath=rootPath or _DEFAULT_ROOT_PATH[provider],
    )


async def createSandbox(ctx: SandboxCtx) -> BaseSandbox:
    """Build the LangChain sandbox backend for ``ctx.providerId``.

    The backend is ``deepagents.backends.sandbox.BaseSandbox`` — provider
    agnostic: callers never import a concrete provider class. When the ctx
    carries a ``sandboxId`` the provider reconnects to that sandbox;
    otherwise it creates a fresh one and writes the id onto the ctx.

    Raises:
        ValueError: the ctx carries an unknown provider id (programmer
            error — the map only ever holds :data:`_SANDBOX_PROVIDERS` keys).
    """
    factory = _SANDBOX_PROVIDERS.get(ctx.providerId)
    if factory is None:
        raise ValueError(f"Unknown sandbox provider: {ctx.providerId!r}")
    return await factory(ctx)


async def killSandbox(ctx: SandboxCtx) -> None:
    """Destroy the sandbox referenced by ``ctx.sandboxId`` (best-effort).

    Raises:
        ValueError: the ctx carries an unknown provider id (programmer
            error — the map only ever holds :data:`_SANDBOX_KILLERS` keys).
    """
    killer = _SANDBOX_KILLERS.get(ctx.providerId)
    if killer is None:
        raise ValueError(f"Unknown sandbox provider: {ctx.providerId!r}")
    await killer(ctx)


__all__ = ["createSandbox", "createSandboxCtx", "killSandbox"]
