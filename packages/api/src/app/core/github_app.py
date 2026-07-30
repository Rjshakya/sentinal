"""GitHub App client factory.

One process-wide :class:`AppAuthStrategy` is built lazily from
``settings``. Call :func:`installation_client` to derive a per-installation
:class:`githubkit.GitHub` that mints and caches its installation token
under the hood.

Module layout:

- :func:`get_app_github` — singleton App-level client.
- :func:`installation_client` — installation-scoped client.
- :func:`list_installation_repos` — typed wrapper for
  ``GET /installation/repositories`` with pagination.
- :func:`mint_installation_token` — explicit token mint (the same token
  the client uses internally; exposed for the indexing pipeline so it
  can clone private repos inside the sandbox).
- :func:`installation_id_for_repo` — owner/repo → ``github_installation_id``,
  used as a fallback when only owner/repo is known.
- :func:`get_installation` — wrapper for ``GET /app/installations/{id}``,
  used by the install-flow setup callback to refresh installation
  metadata.
"""

from __future__ import annotations

import base64
import binascii
import logging
from datetime import datetime
from typing import Optional

from githubkit import GitHub
from githubkit.auth import AppAuthStrategy
from githubkit_schemas.v2026_03_10.models import (
    Installation as GhInstallation,
)
from githubkit_schemas.v2026_03_10.models import (
    InstallationRepositoriesGetResponse200PropRepositoriesItems,
)
from pydantic import BaseModel

from app.core.config import settings

log = logging.getLogger(__name__)


_app_github: GitHub[AppAuthStrategy] | None = None


class InstallationRepo(BaseModel):
    id: int
    name: str
    full_name: str
    owner: str
    private: bool
    description: str | None
    default_branch: str
    html_url: str
    stargazers_count: int
    language: str | None
    updated_at: datetime | None
    clone_url: str


def _resolve_private_key():

    b64 = settings.github_app_private_key
    if b64:
        try:
            return base64.b64decode(b64, validate=True).decode("utf-8")
        except (binascii.Error, ValueError) as exc:
            raise RuntimeError(
                f"Failed to decode GITHUB_APP_PRIVATE_KEY_BASE64: {exc}"
            ) from exc


def get_app_github() -> GitHub[AppAuthStrategy]:
    """Return the process-wide App-level :class:`GitHub` client.

        Lazily constructs the :class:`AppAuthStrategy` from settings. Raises
        :class:`RuntimeError` if any of the four required fields are
    missing.
    """
    global _app_github
    if _app_github is None:
        if not settings.github_app_configured:
            raise RuntimeError(
                "GitHub App is not configured. Set GITHUB_APP_ID, "
                "GITHUB_APP_CLIENT_ID, GITHUB_APP_CLIENT_SECRET, "
                "GITHUB_APP_PRIVATE_KEY, and GITHUB_APP_SLUG in .env"
            )
        _app_github = GitHub(
            AppAuthStrategy(
                app_id=settings.github_app_id,
                private_key=_resolve_private_key() or "",
                client_id=settings.github_app_client_id,
                client_secret=settings.github_app_client_secret,
            )
        )
    return _app_github


def installation_client(installation_id: int) -> GitHub:
    """Derive an installation-scoped :class:`GitHub` from the App client.

    The returned client mints a fresh installation token on first use
    and caches it until near-expiry — the caller does not need to
    manage token lifecycle.
    """
    app = get_app_github()
    return app.with_auth(app.auth.as_installation(installation_id))


def _repo_payload(
    repo: InstallationRepositoriesGetResponse200PropRepositoriesItems,
) -> InstallationRepo:
    """Flatten a githubkit repository model into the :class:`RepoOut` shape."""

    return InstallationRepo(
        id=repo.id,
        name=repo.name,
        full_name=repo.full_name,
        owner=repo.owner.login if repo.owner is not None else "",
        private=repo.private,
        description=repo.description,
        default_branch=repo.default_branch,
        html_url=repo.html_url,
        stargazers_count=repo.stargazers_count,
        language=repo.language,
        updated_at=repo.updated_at,
        clone_url=repo.clone_url,
    )


async def list_installation_repos(installation_id: int) -> list[InstallationRepo]:
    """Return every repo the installation can access.

    Paginates through ``GET /installation/repositories`` and yields
    the flat dict the :class:`RepoOut` response model expects. The
    caller is responsible for attaching the surrounding
    ``installation_id`` (the local uuid) before returning to the
    client.
    """
    client = installation_client(installation_id)
    page = 1
    out: list[InstallationRepo] = []
    while True:
        resp = await client.rest.apps.async_list_repos_accessible_to_installation(
            per_page=100,
            page=page,
        )
        data = resp.parsed_data
        if data is None:
            break
        for repo in data.repositories or []:
            out.append(_repo_payload(repo))
        if data.total_count and len(out) >= data.total_count:
            break
        if not data.repositories or len(data.repositories) < 100:
            break
        page += 1
    return out


async def mint_installation_token(installation_id: int) -> str:
    """Force-mint a fresh installation access token.

    The :class:`AppAuthStrategy` caches the token internally on the
    installation client, so repeated calls with the same
    ``installation_id`` are cheap. Exposed for the indexing pipeline,
    which needs the raw token to pass into the sandbox as
    ``GITHUB_TOKEN``.

    Note: this endpoint requires App-level auth (JWT), so we use the
    App client — not the installation-scoped one.
    """
    app = get_app_github()
    resp = await app.rest.apps.async_create_installation_access_token(
        installation_id,
    )
    parsed = resp.parsed_data
    if parsed is None or not getattr(parsed, "token", None):
        raise RuntimeError(
            f"GitHub returned no installation token for installation_id={installation_id}"
        )
    return parsed.token


async def installation_id_for_repo(owner: str, repo: str) -> int | None:
    """Resolve ``owner/repo`` to the App's ``github_installation_id``.

    Used as a fallback when the dashboard only knows owner/repo (not
    the local :class:`Installation` row). Returns ``None`` if the App
    has no installation for that repo.
    """
    app = get_app_github()
    try:
        resp = await app.rest.apps.async_get_repo_installation(owner=owner, repo=repo)
    except Exception as exc:
        log.warning(
            "githubkit: get_repo_installation failed for %s/%s: %s",
            owner,
            repo,
            exc,
        )
        return None
    data = resp.parsed_data
    return getattr(data, "id", None)


class InstallationDetails(BaseModel):
    """Flat view of a GitHub App installation, derived from ``GhInstallation``."""

    id: int
    account_login: str
    account_type: str
    repository_selection: str
    suspended_at: Optional[datetime] = None


def _flatten_installation(payload: GhInstallation) -> InstallationDetails:
    """Project a :class:`GhInstallation` onto the flat :class:`InstallationDetails`."""
    account = payload.account
    account_login: str = ""
    account_type: str = ""
    if account is not None:
        account_login = getattr(account, "login", "") or ""
        account_type = getattr(account, "type", "") or ""
    return InstallationDetails(
        id=payload.id,
        account_login=account_login,
        account_type=account_type,
        repository_selection=payload.repository_selection,
        suspended_at=payload.suspended_at,
    )


async def get_installation(installation_id: int) -> InstallationDetails:
    """Fetch a single installation by id via the App-level client.

    Thin wrapper over ``GET /app/installations/{installation_id}``.
    Returns a flat :class:`InstallationDetails`. Raises on HTTP errors
    so the caller (the setup callback) can 302 to a failure redirect.
    """
    app = get_app_github()
    resp = await app.rest.apps.async_get_installation(installation_id=installation_id)
    parsed = resp.parsed_data
    if parsed is None:
        raise RuntimeError(
            f"GitHub returned no installation payload for installation_id={installation_id}"
        )
    return _flatten_installation(parsed)
