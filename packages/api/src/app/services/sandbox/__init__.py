"""Sandbox service: provider-pluggable sandbox contexts and lifecycle.

Entry points:

- :func:`createSandboxCtx` — assemble a serializable :class:`SandboxCtx`
  (data only: user, repo, provider, key, ids, root path).
- :func:`createSandbox` — provider map: build LangChain's sandbox backend
  (``deepagents.backends.sandbox.BaseSandbox``) for a ctx's ``providerId``.
- :func:`killSandbox` — provider map: destroy the sandbox referenced by a
  ctx's ``sandboxId`` (best-effort).

Naming convention: this package intentionally uses **camelCase**
identifiers to mirror the ctx-shaped API it exposes — it is the one
camelCase island in the codebase.
"""

from app.services.sandbox.service import createSandbox, createSandboxCtx, killSandbox
from app.services.sandbox.types import (
    ApiKey,
    ProviderId,
    RepoId,
    SandboxCtx,
    SandboxId,
    UserId,
)

__all__ = [
    "ApiKey",
    "ProviderId",
    "RepoId",
    "SandboxCtx",
    "SandboxId",
    "UserId",
    "createSandbox",
    "createSandboxCtx",
    "killSandbox",
]