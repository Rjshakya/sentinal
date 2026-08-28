"""Installation sub-service: GitHub App install flow + local state.

Entry points (camelCase, matching the package convention):

- :func:`createInstallationCtx` — ctx factory: mints the installation
  client and assembles the ctx (the I/O boundary).
- :func:`getInstallUrl` — signed install URL for the browser.
- :func:`getInstallation` — installation details from the GitHub API.
- :func:`listInstallations` — the user's local ``installations`` rows.
- :func:`forgetInstallation` — local forget (delete rows; the user must
  still uninstall the App on github.com).

Error contract: **no function raises.** Expected failures are returned
as :class:`GitHubInstallationError` values; callers discriminate with
``isinstance``.

DB: :func:`listInstallations` / :func:`forgetInstallation` read/write
the local ``installations`` table and take an :class:`AsyncSession`
from the caller. GitHub API calls use the client carried on the ctx,
minted by :func:`createInstallationCtx` at the edge; App-level calls
(:func:`getInstallation`) use the process-wide App client
(:mod:`app.services.github._client`).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import time
from typing import cast
from urllib.parse import quote

from sqlalchemy.sql.elements import ColumnElement
from sqlmodel import delete, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.models.installation import Installation
from app.services.github.client import getAppGitHub, getAuthenticatedGitHubClient
from app.services.github.installation.errors import GitHubInstallationError
from app.services.github.installation.types import (
    InstallationCtx,
    InstallationDetails,
    InstallUrl,
)
from app.utils.branded import InstallationId, UserId

_STATE_TTL_S: int = 600
"""How long a signed install-flow state token stays valid."""


def signState(userId: str, secret: str) -> str:
    """Sign the install-flow state token (HMAC-SHA256, stdlib only).

    Shape: ``base64url(payload) "." base64url(hmac_sha256(secret, payload))``
    with payload ``"{user_id}|{exp_unix_seconds}"``.
    """
    payload = f"{userId}|{int(time.time()) + _STATE_TTL_S}".encode("utf-8")
    raw = base64.urlsafe_b64encode(payload).rstrip(b"=").decode("ascii")
    mac = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).digest()
    sig = base64.urlsafe_b64encode(mac).rstrip(b"=").decode("ascii")
    return f"{raw}.{sig}"


def createInstallationCtx(
    userId: UserId,
    installationId: InstallationId,
) -> InstallationCtx:
    """Assemble an :class:`InstallationCtx`.

    The installation-scoped client is minted here — the ctx factory is
    the I/O boundary ("edge"). Identity is validated upstream (auth
    middleware / webhook receiver), so no checks happen here.
    """
    return InstallationCtx(
        userId=userId,
        installationId=installationId,
        client=getAuthenticatedGitHubClient(installationId),
    )


def getInstallUrl(userId: UserId) -> InstallUrl:
    """Mint the signed GitHub App install URL for the browser.

    The state token carries the WorkOS ``user_id`` (HMAC-signed, TTL
    :data:`_STATE_TTL_S`); GitHub round-trips it to the setup callback.
    The App env vars are validated at app startup.
    """
    secret = settings.github_install_state_effective_secret
    state = signState(userId, secret)
    slug = settings.github_app_slug
    url = (
        f"https://github.com/apps/{slug}/installations/new"
        f"?state={quote(state, safe='')}"
    )
    return InstallUrl(url=url)


async def getInstallation(
    ctx: InstallationCtx,
) -> InstallationDetails | GitHubInstallationError:
    """Fetch a single installation's details from the GitHub API."""
    app = getAppGitHub()

    try:
        resp = await app.rest.apps.async_get_installation(
            installation_id=ctx.installationId
        )
    except Exception as exc:
        cause = f"{type(exc).__name__}: {exc}"

        return GitHubInstallationError(
            message=f"failed to fetch installation: {cause}",
            userId=ctx.userId,
            installationId=ctx.installationId,
        )

    parsed = resp.parsed_data
    if parsed is None:
        return GitHubInstallationError(
            message="github returned an empty installation payload",
            userId=ctx.userId,
            installationId=ctx.installationId,
        )
    return _toInstallationDetails(parsed)


def _toInstallationDetails(parsed: object) -> InstallationDetails:
    """Project a githubkit ``Installation`` onto :class:`InstallationDetails`."""
    account = getattr(parsed, "account", None)
    return InstallationDetails(
        id=InstallationId(getattr(parsed, "id", 0) or 0),
        accountLogin=getattr(account, "login", None) or "",
        accountType=getattr(account, "type", None) or "",
        repositorySelection=getattr(parsed, "repository_selection", None) or "",
        suspendedAt=getattr(parsed, "suspended_at", None),
    )


async def listInstallations(
    session: AsyncSession,
    ctx: InstallationCtx,
) -> list[InstallationDetails] | GitHubInstallationError:
    """Return the user's local ``installations`` rows, newest first.

    Reads the local mirror — the GitHub API is not consulted. The
    ``suspended`` flag is derived from ``suspended_at`` at the boundary.
    """
    stmt = (
        select(Installation)
        .where(Installation.user_id == ctx.userId)
        .order_by(Installation.created_at.desc())  # type: ignore[attr-defined]
    )
    try:
        rows = (await session.exec(stmt)).all()
    except Exception as exc:
        cause = f"{type(exc).__name__}: {exc}"

        return GitHubInstallationError(
            message=f"failed to list installations: {cause}",
            userId=ctx.userId,
        )

    return [
        InstallationDetails(
            id=InstallationId(row.github_installation_id),
            accountLogin=row.account_login,
            accountType=row.account_type,
            repositorySelection=row.repository_selection,
            suspendedAt=row.suspended_at,
        )
        for row in rows
    ]


async def forgetInstallation(
    session: AsyncSession,
    ctx: InstallationCtx,
) -> None | GitHubInstallationError:
    """Locally forget an installation: delete its ``installations`` rows.

    Keyed on ``(github_installation_id, user_id)``. The user must still
    uninstall the App on github.com; this only clears Sentinel's local
    state. Returns an error when no row matched (nothing to forget).
    """
    stmt = delete(Installation).where(
        cast(
            ColumnElement[bool],
            Installation.github_installation_id == ctx.installationId,
        ),
        cast(ColumnElement[bool], Installation.user_id == ctx.userId),
    )
    try:
        result = await session.exec(stmt)
        await session.commit()
    except Exception as exc:
        await session.rollback()
        cause = f"{type(exc).__name__}: {exc}"

        return GitHubInstallationError(
            message=f"failed to forget installation: {cause}",
            userId=ctx.userId,
            installationId=ctx.installationId,
        )

    if (result.rowcount or 0) == 0:
        return GitHubInstallationError(
            message="installation not found",
            userId=ctx.userId,
            installationId=ctx.installationId,
        )
    return None


__all__ = [
    "createInstallationCtx",
    "forgetInstallation",
    "getInstallUrl",
    "getInstallation",
    "listInstallations",
]
