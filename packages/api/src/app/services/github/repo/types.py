"""Repo sub-service types: ctx + result models.

This module owns the contract of the repo sub-service: the
:class:`RepoCtx` (identity + injected client) and the
:class:`GitHubRepo` projection of GitHub's repository payload.

Naming convention: this package intentionally uses **camelCase**
identifiers — the same convention as :mod:`app.services.llm` and
:mod:`app.services.sandbox`. Ids that are also identifiers (id, ctx)
keep their single-word lowercase form.

Design notes:

- :class:`RepoCtx` is a plain Pydantic model carrying identity plus the
  installation-scoped githubkit client, minted by the ctx factory
  (:func:`app.services.github.repo.service.createRepoCtx`) at the edge.
  Not serializable — tests build the ctx directly with a mock client.
- Ids are **branded types** (``NewType`` over ``str`` / ``int`` from
  :mod:`app.utils.branded`): they erase at runtime (Pydantic validation
  is unaffected) but pyright enforces the branding statically, so a
  bare ``int`` cannot accidentally flow into a ctx.
"""

from __future__ import annotations

from datetime import datetime

from githubkit import GitHub
from pydantic import BaseModel, ConfigDict

from app.utils.branded import InstallationId, RepoName, RepoOwner, UserId


class RepoCtx(BaseModel):
    """Identity of one GitHub repository under one installation + its client."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    userId: UserId
    installationId: InstallationId
    owner: RepoOwner
    repo: RepoName
    client: GitHub


class GitHubRepo(BaseModel):
    """Flat projection of a GitHub repository."""

    id: int
    name: str
    fullName: str
    owner: str
    private: bool
    description: str | None = None
    defaultBranch: str
    htmlUrl: str
    stargazersCount: int = 0
    language: str | None = None
    updatedAt: datetime | None = None
    cloneUrl: str


__all__ = ["GitHubRepo", "RepoCtx"]