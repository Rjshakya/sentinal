"""Installation sub-service types: ctx + result models.

This module owns the contract of the installation sub-service: the
:class:`InstallationCtx` (identity + injected client) and the result
projections (:class:`InstallUrl`, :class:`InstallationDetails`).

Naming convention: this package intentionally uses **camelCase**
identifiers — the same convention as :mod:`app.services.llm` and
:mod:`app.services.sandbox`. Ids that are also identifiers (id, ctx)
keep their single-word lowercase form.

Design notes:

- :class:`InstallationCtx` is a plain Pydantic model carrying identity
  plus the installation-scoped githubkit client, minted by the ctx
  factory (:func:`app.services.github.installation.service.createInstallationCtx`)
  at the edge. Not serializable — tests build the ctx directly with a
  mock client.
- Ids are **branded types** (``NewType`` over ``str`` / ``int`` from
  :mod:`app.utils.branded`): they erase at runtime (Pydantic validation
  is unaffected) but pyright enforces the branding statically, so a
  bare ``int`` cannot accidentally flow into a ctx.
"""

from __future__ import annotations

from datetime import datetime

from githubkit import GitHub
from pydantic import BaseModel, ConfigDict

from app.utils.branded import InstallationId, UserId


class InstallationCtx(BaseModel):
    """Identity of one GitHub App installation + its client."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    userId: UserId
    installationId: InstallationId
    client: GitHub


class InstallUrl(BaseModel):
    """Signed GitHub App install URL for the browser."""

    url: str


class InstallationDetails(BaseModel):
    """Flat view of a GitHub App installation."""

    id: InstallationId
    accountLogin: str
    accountType: str
    repositorySelection: str
    suspendedAt: datetime | None = None


__all__ = ["InstallationCtx", "InstallationDetails", "InstallUrl"]