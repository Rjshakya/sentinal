"""Provider-pluggable sandbox service types.

This module owns the *contract* of the sandbox service: the serializable
:class:`SandboxCtx` (pure data — everything a run needs) and the branded
identifier types it carries.

Naming convention: this package intentionally uses **camelCase**
identifiers to mirror the ctx-shaped API it exposes — it is the one
camelCase island in the codebase. Identifiers that are also identifiers
(id, ctx) keep their single-word lowercase form.

Design notes:

- :class:`SandboxCtx` is a plain Pydantic model (DBOS-serializable) so it
  can cross workflow boundaries (the review pipeline will embed it in its
  run context). It carries every datum a run needs — user, repo, provider,
  key, sandbox id, name, root path — and nothing else.
- Ids and keys are **branded types** (``NewType`` over ``str``): they
  erase to ``str`` at runtime (Pydantic validation and DBOS serialization
  are unaffected) but pyright enforces the branding statically, so a bare
  ``str`` cannot accidentally flow into a ctx.
- Sandbox instances are never part of the contract: the provider map
  (:func:`app.services.sandbox.service.createSandbox`) returns LangChain's
  sandbox backend (``deepagents.backends.sandbox.BaseSandbox``) for a ctx's
  ``providerId``, so no provider-specific class is defined or imported
  here. Lifecycle (create/connect/kill) is owned by the LangChain provider
  objects, not by this package.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Coroutine, Literal, Type

from deepagents.backends.sandbox import BaseSandbox
from pydantic import BaseModel

from app.services.sandbox.errors import SandboxProviderError
from app.utils.branded import RepoId, SanboxProviderApiKey, SandboxId, UserId


class BaseSandboxService(ABC):

    @abstractmethod
    def __init__(self, ctx: SandboxCtx) -> None: ...

    @abstractmethod
    async def create(self) -> BaseSandbox | SandboxProviderError: ...

    @abstractmethod
    async def connect(self) -> None | SandboxProviderError: ...

    @abstractmethod
    async def kill(self) -> None | SandboxProviderError: ...


ProviderId = Literal["e2b", "daytona"]
"""The supported sandbox providers."""

ProviderMap = dict[ProviderId, Type[BaseSandboxService]]


class SandboxCtx(BaseModel):
    """Everything a sandbox run needs, as pure serializable data.

    The ctx is assembled by
    :func:`app.services.sandbox.service.createSandboxCtx`; the provider map
    (:func:`app.services.sandbox.service.createSandbox`) consumes it to
    create or reconnect LangChain's sandbox backend and writes the
    provider-assigned id onto :attr:`sandboxId` when a new sandbox is
    created.
    """

    userId: UserId
    repoId: RepoId
    repoName: str
    providerId: ProviderId = "e2b"
    apiKey: SanboxProviderApiKey | None = None
    sandboxId: SandboxId | None = None
    sandboxName: str
    rootPath: str = "/home/user"
    """Working directory the provider's sandbox backend runs commands from."""


__all__ = [
    "ProviderId",
    "RepoId",
    "SanboxProviderApiKey",
    "SandboxCtx",
    "SandboxId",
    "UserId",
]
