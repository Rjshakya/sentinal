"""Repo sub-service: reading repos from GitHub.

Public surface:

- :func:`createRepoCtx` — ctx constructor.
- :func:`listInstallationRepos` — paginated repo list for an installation.
- :func:`getRepo` — single repo.
- :func:`mintAccessToken` — fresh installation access token.
- :func:`getCloneUrl` — authenticated https clone URL.

Error contract: **no function raises.** Failures are returned as
:class:`GitHubRepoError` values; callers discriminate with
``isinstance``.
"""

from app.services.github.repo.errors import GitHubRepoError
from app.services.github.repo.service import (
    createRepoCtx,
    getCloneUrl,
    getRepo,
    listInstallationRepos,
    mintAccessToken,
)
from app.services.github.repo.types import GitHubRepo, RepoCtx

__all__ = [
    "GitHubRepo",
    "GitHubRepoError",
    "RepoCtx",
    "createRepoCtx",
    "getCloneUrl",
    "getRepo",
    "listInstallationRepos",
    "mintAccessToken",
]