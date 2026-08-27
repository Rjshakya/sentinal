"""Typed errors for the installation sub-service.

All errors are :class:`BaseModel` values **returned** (never raised)
by :mod:`app.services.github.installation.service` entry points;
callers discriminate with ``isinstance``.
"""

from __future__ import annotations

from pydantic import BaseModel

from app.utils.branded import InstallationId, UserId


class GitHubInstallationError(BaseModel):
    """Error variant of every ``T | GitHubInstallationError`` union in
    the installation sub-service."""

    message: str
    userId: UserId | None = None
    installationId: InstallationId | None = None
    id: str | None = None

    def __str__(self) -> str:
        return self.message


__all__ = ["GitHubInstallationError"]