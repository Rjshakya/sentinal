"""Repo sub-service: reading repos from GitHub.

Entry points (camelCase, matching the package convention):

- :func:`createRepoCtx` — ctx factory: mints the installation client
  and assembles the ctx (the I/O boundary).
- :func:`listInstallationRepos` — paginated ``GET /installation/repositories``
  for the ctx's installation.
- :func:`getRepo` — single repo via ``GET /repos/{owner}/{repo}``.
- :func:`mintAccessToken` — fresh installation access token
  (``POST /app/installations/{id}/access_tokens``).
- :func:`getCloneUrl` — authenticated https clone URL from a minted
  token (pure, no I/O).

Error contract: **no function raises.** Expected failures are returned
as :class:`GitHubRepoError` values; callers discriminate with
``isinstance``. GitHub API calls use the client carried on the ctx,
minted by :func:`createRepoCtx` at the edge; the App-level token mint
(:func:`mintAccessToken`) uses the process-wide App client
(:mod:`app.services.github._client`).
"""

from __future__ import annotations

from githubkit_schemas.v2026_03_10.models import FullRepository

from app.services.github.client import getAppGitHub, getAuthenticatedGitHubClient
from app.services.github.repo.errors import GitHubRepoError
from app.services.github.repo.types import GitHubRepo, RepoCtx
from app.utils.branded import AccessToken, InstallationId, RepoName, RepoOwner, UserId

_PAGE_SIZE: int = 100
"""Repos per page for the paginated installation listing."""


def createRepoCtx(
    userId: UserId,
    installationId: InstallationId,
    owner: RepoOwner,
    repo: RepoName,
) -> RepoCtx:
    """Assemble a :class:`RepoCtx`.

    The installation-scoped client is minted here — the ctx factory is
    the I/O boundary ("edge"). Identity is validated upstream (auth
    middleware / webhook receiver), so no checks happen here.
    """
    return RepoCtx(
        userId=userId,
        installationId=installationId,
        owner=owner,
        repo=repo,
        client=getAuthenticatedGitHubClient(installationId),
    )


async def listInstallationRepos(
    ctx: RepoCtx,
) -> list[GitHubRepo] | GitHubRepoError:
    """Return every repo the ctx's installation can access.

    Paginates through ``GET /installation/repositories`` (100 per
    page) and stops on the ``total_count`` or an exhausted page.
    """
    client = ctx.client

    page = 1
    out: list[GitHubRepo] = []
    while True:
        try:
            resp = await client.rest.apps.async_list_repos_accessible_to_installation(
                per_page=_PAGE_SIZE,
                page=page,
            )
        except Exception as exc:
            cause = f"{type(exc).__name__}: {exc}"

            return GitHubRepoError(
                message=f"failed to list repos: {cause}",
                userId=ctx.userId,
                installationId=ctx.installationId,
            )

        parsed = resp.parsed_data
        if parsed is None:
            break
        items = getattr(parsed, "repositories", None) or []
        out.extend(_toGitHubRepo(item) for item in items)

        total = getattr(parsed, "total_count", None)
        if total is not None and len(out) >= int(total):
            break
        if len(items) < _PAGE_SIZE:
            break
        page += 1

    return out


async def getRepo(ctx: RepoCtx) -> GitHubRepo | GitHubRepoError:
    """Fetch a single repo via ``GET /repos/{owner}/{repo}``."""
    client = ctx.client

    try:
        resp = await client.rest.repos.async_get(owner=ctx.owner, repo=ctx.repo)
    except Exception as exc:
        cause = f"{type(exc).__name__}: {exc}"
        return GitHubRepoError(
            message=f"failed to fetch repo: {cause}",
            userId=ctx.userId,
            installationId=ctx.installationId,
            owner=ctx.owner,
            repo=ctx.repo,
        )

    parsed = resp.parsed_data
    if parsed is None:
        return GitHubRepoError(
            message="github returned an empty repo payload",
            userId=ctx.userId,
            installationId=ctx.installationId,
            owner=ctx.owner,
            repo=ctx.repo,
        )
    return _toGitHubRepo(parsed)


async def mintAccessToken(ctx: RepoCtx) -> AccessToken | GitHubRepoError:
    """Force-mint a fresh installation access token.

    Uses the App-level client (JWT auth) — installation tokens are
    minted by the App, not the installation.
    """
    app = getAppGitHub()

    try:
        resp = await app.rest.apps.async_create_installation_access_token(
            ctx.installationId
        )
    except Exception as exc:
        cause = f"{type(exc).__name__}: {exc}"
        return GitHubRepoError(
            message=f"failed to mint installation token: {cause}",
            userId=ctx.userId,
            installationId=ctx.installationId,
            owner=ctx.owner,
            repo=ctx.repo,
        )

    parsed = resp.parsed_data
    token = getattr(parsed, "token", None)
    if parsed is None or not token:
        return GitHubRepoError(
            message="github returned no installation token",
            userId=ctx.userId,
            installationId=ctx.installationId,
            owner=ctx.owner,
            repo=ctx.repo,
        )
    return AccessToken(token)


def getCloneUrl(ctx: RepoCtx, token: AccessToken) -> str:
    """Build the authenticated https clone URL for the repo.

    Pure — no I/O. The caller decides when/how to mint ``token``
    (typically via :func:`mintAccessToken`).
    """
    return f"https://x-access-token:{token}@github.com/{ctx.owner}/{ctx.repo}.git"


def _toGitHubRepo(parsed: FullRepository) -> GitHubRepo:
    """Project a githubkit ``Repository`` onto :class:`GitHubRepo`."""
    owner = getattr(parsed, "owner", None)

    return GitHubRepo(
        id=int(getattr(parsed, "id", 0) or 0),
        name=getattr(parsed, "name", None) or "",
        fullName=getattr(parsed, "full_name", None) or "",
        owner=getattr(owner, "login", None) or "",
        private=bool(getattr(parsed, "private", False)),
        description=getattr(parsed, "description", None),
        defaultBranch=getattr(parsed, "default_branch", None) or "",
        htmlUrl=getattr(parsed, "html_url", None) or "",
        stargazersCount=int(getattr(parsed, "stargazers_count", 0) or 0),
        language=getattr(parsed, "language", None),
        updatedAt=getattr(parsed, "updated_at", None),
        cloneUrl=getattr(parsed, "clone_url", None) or "",
    )


__all__ = [
    "createRepoCtx",
    "getCloneUrl",
    "getRepo",
    "listInstallationRepos",
    "mintAccessToken",
]
