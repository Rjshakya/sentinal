"""Step: resolve the authenticated clone URL for ``owner/repo``.

Private-repo support for the indexing pipeline. The public
``repo_url`` from :class:`IndexWorkflowInput` cannot clone a private
repo, so this step resolves the repo's GitHub installation and mints
an installation access token to build an authenticated clone URL via
:func:`app.services.setup._helpers.build_authenticated_clone_url`
(the same primitive the setup pipeline uses).

Sequence:

1. Look up the :class:`Installation` row by ``(user_id,
   ``account_login == repo_owner``)`` — the GitHub account that owns
   the repo. GitHub allows one installation per account per App, so
   the match is unique. A missing row is a final
   :class:`IndexInstallationNotFoundError` (no token can be minted).
2. Mint a fresh installation token via
   :func:`app.core.github_app.mint_installation_token`. Exceptions
   are wrapped in :class:`IndexInstallTokenMintError` (transient) so
   DBOS retries GitHub 5xx / network blips.
3. Build and return the authenticated clone URL.

DBOS keys step registration on ``__name__``. Named ``getRepoUrl``
(camelCase) so it does not collide with the setup pipeline's
snake_case ``mint_installation_token_step``.
"""

from __future__ import annotations

import logging

from dbos import DBOS
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.db import async_session_maker
from app.core.github_app import mint_installation_token
from app.models.installation import Installation
from app.services.indexing.errors import (
    IndexInstallationNotFoundError,
    IndexInstallTokenMintError,
    _should_retry_index,
)
from app.services.setup._helpers import build_authenticated_clone_url

log = logging.getLogger(__name__)


async def _find_github_installation_id(
    *,
    session: AsyncSession,
    user_id: str,
    account_login: str,
) -> int | None:
    """Return the GitHub-side installation id for the account, or ``None``.

    Single ``SELECT github_installation_id FROM installations WHERE
    user_id = ? AND account_login = ?``. The ``user_id`` predicate is
    enforced at the DB layer; if a row matches the account login but
    belongs to a different user we get no hit.
    """
    stmt = select(Installation.github_installation_id).where(
        Installation.user_id == user_id,
        Installation.account_login == account_login,
    )
    result = await session.exec(stmt)
    return result.first()


@DBOS.step(
    retries_allowed=True,
    max_attempts=3,
    should_retry=_should_retry_index,
)
async def getRepoUrl(
    *,
    user_id: str,
    repo_owner: str,
    repo_name: str,
) -> str:
    """Resolve the authenticated clone URL for ``repo_owner/repo_name``.

    Looks up the repo's installation by ``account_login == repo_owner``,
    mints a fresh installation token, and embeds it in the HTTPS clone
    URL. The caller passes the returned URL to
    :func:`gitCloneToSandbox` (``clone_url``), which uses it in place
    of the public ``repo_url`` from the input.

    Returns:
        The authenticated clone URL as a plain ``str``
        (``https://x-access-token:<token>@github.com/{owner}/{name}.git``).

    Raises:
        IndexInstallationNotFoundError: no :class:`Installation` row
            matches ``(user_id, repo_owner)``. Final — not retried.
        IndexInstallTokenMintError: the token mint failed. Transient —
            retried by DBOS up to ``max_attempts`` times.
    """
    try:
        async with async_session_maker() as session:
            github_installation_id = await _find_github_installation_id(
                session=session,
                user_id=user_id,
                account_login=repo_owner,
            )
    except Exception as exc:
        log.warning(
            "getRepoUrl: installation lookup failed user_id=%s owner=%s repo=%s cause=%s: %s",
            user_id,
            repo_owner,
            repo_name,
            type(exc).__name__,
            exc,
        )
        raise IndexInstallTokenMintError(
            cause=f"installation lookup failed: {type(exc).__name__}: {exc}"
        ) from exc

    if github_installation_id is None:
        raise IndexInstallationNotFoundError(
            user_id=user_id,
            repo_owner=repo_owner,
            repo_name=repo_name,
        )

    try:
        token = await mint_installation_token(github_installation_id)
    except Exception as exc:
        log.warning(
            "getRepoUrl: token mint failed installation_id=%s owner=%s repo=%s cause=%s: %s",
            github_installation_id,
            repo_owner,
            repo_name,
            type(exc).__name__,
            exc,
        )
        raise IndexInstallTokenMintError(cause=f"{type(exc).__name__}: {exc}") from exc

    clone_url = build_authenticated_clone_url(
        install_token=token,
        owner=repo_owner,
        name=repo_name,
    )

    log.info(
        "getRepoUrl: ok owner=%s repo=%s installation_id=%s",
        repo_owner,
        repo_name,
        github_installation_id,
    )
    return clone_url


__all__ = ["getRepoUrl"]

