"""Typed errors for the repo sub-service.

All errors are :class:`BaseModel` values **returned** (never raised)
by :mod:`app.services.github.repo.service` entry points; callers
discriminate with ``isinstance``.
"""

from __future__ import annotations

from pydantic import BaseModel

from app.utils.branded import InstallationId, RepoName, RepoOwner, UserId


class GitHubRepoError(BaseModel):
    """Error variant of every ``T | GitHubRepoError`` union in the
    repo sub-service."""

    message: str
    userId: UserId | None = None
    installationId: InstallationId | None = None
    owner: RepoOwner | None = None
    repo: RepoName | None = None
    id: str | None = None

    def __str__(self) -> str:
        return self.message


__all__ = ["GitHubRepoError"]