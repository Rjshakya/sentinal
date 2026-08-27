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

from abc import ABC, abstractmethod
import logging
from collections.abc import Awaitable, Callable
from typing import cast

import e2b
from deepagents.backends.sandbox import BaseSandbox
from e2b.sandbox.sandbox_api import SandboxLifecycle as E2BSandboxLifecycle
from langchain_e2b import AsyncE2BSandbox

from app.core.config import settings
from app.core.sandbox.e2b import CODE_SANDBOX_TEMPLATE_NAME
from app.services.sandbox.e2b import E2BService
from app.services.sandbox.errors import SandboxProviderError
from app.services.sandbox.types import (
    ProviderId,
    ProviderMap,
    RepoId,
    SanboxProviderApiKey,
    SandboxCtx,
    SandboxId,
    UserId,
)
from abc import ABC, abstractmethod

log = logging.getLogger(__name__)

DEFAULT_ROOT_PATH: dict[ProviderId, str] = {
    "e2b": "/home/user",
    "daytona": "/sentinel-workspace",
}


def getDefaulSandboxName(repoName: str) -> str:
    return f"{repoName}-sandbox"


def getDefaulProvider() -> ProviderId:
    return cast(ProviderId, "e2b")


def createSandboxCtx(
    *,
    userId: UserId,
    repoId: RepoId,
    repoName: str,
    providerId: ProviderId,
    apiKey: SanboxProviderApiKey,
    sandboxName: str,
    rootPath: str,
) -> SandboxCtx:
    """Assemble a :class:`SandboxCtx` with settings-driven defaults.

    Defaults:
    - ``providerId`` — :attr:`app.core.config.Settings.sandbox_provider`.
    - ``apiKey``     — the provider's env key (``E2B_API_KEY`` /
      ``DAYTONA_API_KEY``); ``None`` when unset. The map entries pass this
      key to the provider SDK on every lifecycle call.
    - ``rootPath``   — the provider's default workdir (``/home/user`` for
      e2b, ``/sentinel-workspace`` for daytona).
    """
    return SandboxCtx(
        userId=userId,
        repoId=repoId,
        repoName=repoName,
        providerId=providerId,
        apiKey=apiKey,
        sandboxName=sandboxName,
        rootPath=rootPath,
    )


Providers: ProviderMap = {"e2b": E2BService}


def get_provider(providerId: ProviderId):
    provider = Providers.get(providerId)
    if provider is None:
        raise Exception("Unknown provider")
    return provider


__all__ = [
    "createSandboxCtx",
]
