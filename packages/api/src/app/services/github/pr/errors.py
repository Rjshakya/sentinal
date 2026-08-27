"""Typed errors for the pr sub-service.

All errors are :class:`BaseModel` values **returned** (never raised)
by :mod:`app.services.github.pr.service` entry points; callers
discriminate with ``isinstance``.
"""

from __future__ import annotations

from pydantic import BaseModel

from app.utils.branded import (
    InstallationId,
    PRNumber,
    RepoName,
    RepoOwner,
    UserId,
)


class GitHubPRError(BaseModel):
    """Error variant of every ``T | GitHubPRError`` union in the
    pr sub-service."""

    message: str
    userId: UserId | None = None
    installationId: InstallationId | None = None
    owner: RepoOwner | None = None
    repo: RepoName | None = None
    prNumber: PRNumber | None = None
    statusCode: int | None = None

    def __str__(self) -> str:
        return self.message


__all__ = ["GitHubPRError"]