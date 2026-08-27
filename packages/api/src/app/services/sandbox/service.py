"""Sandbox service: ctx assembly + provider map.

Two entry points:

- :func:`createSandboxCtx` — assemble the serializable run context.
  The settings-driven defaults (:func:`getDefaulProvider`,
  :func:`getDefaulSandboxName`, per-provider root path) are resolved
  at the edge so callers only pass what they actually know.
- :data:`Providers` — the provider map: each entry is a concrete
  provider class (:mod:`app.services.sandbox.e2b`) owning the
  lifecycle (create / connect / kill) for a ``providerId``.
  :func:`get_provider` resolves the class for a ctx's ``providerId``.

Credentials: :attr:`SandboxCtx.apiKey` is resolved from settings at
the edge (``E2B_API_KEY`` / ``DAYTONA_API_KEY``) and passed to the
provider SDK on every lifecycle call — the ctx stays the single
source of truth.
"""

from __future__ import annotations

from typing import cast

from app.services.sandbox.e2b import E2BService
from app.services.sandbox.types import (
    ProviderId,
    ProviderMap,
    RepoId,
    SanboxProviderApiKey,
    SandboxCtx,
    UserId,
)

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
    """Assemble a :class:`SandboxCtx`.

    Provider, api key, sandbox name, and root path are resolved at the
    edge (settings-driven defaults via :func:`getDefaulProvider` /
    :func:`getDefaulSandboxName` / :data:`DEFAULT_ROOT_PATH`).
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
    "getDefaulProvider",
    "getDefaulSandboxName",
]