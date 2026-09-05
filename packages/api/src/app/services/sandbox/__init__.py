"""Sandbox service: provider-pluggable sandbox contexts.

Public surface:

- :func:`createSandboxCtx` — assemble a serializable :class:`SandboxCtx`
  (data only: user, repo, provider, key, ids, root path).
- :func:`getDefaulProvider` / :func:`getDefaulSandboxName` — the
  settings-driven defaults used when assembling the ctx at the edge.
- :data:`app.services.sandbox.service.Providers` — the provider map
  wiring lifecycle classes per provider.

Naming convention: this package intentionally uses **camelCase**
identifiers to mirror the ctx-shaped API it exposes — it is the one
camelCase island in the codebase.
"""

from app.services.sandbox.errors import SandboxProviderError
from app.services.sandbox.service import (
    createSandboxCtx,
    getDefaulProvider,
    getDefaulSandboxName,
)
from app.services.sandbox.types import (
    ProviderId,
    RepoId,
    SanboxProviderApiKey,
    SandboxCtx,
    SandboxId,
    UserId,
)

__all__ = [
    "ProviderId",
    "RepoId",
    "SanboxProviderApiKey",
    "SandboxCtx",
    "SandboxId",
    "SandboxProviderError",
    "UserId",
    "createSandboxCtx",
    "getDefaulProvider",
    "getDefaulSandboxName",
]