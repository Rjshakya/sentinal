### packages/api/src/app/services/indexing/steps/get_repo_url.py

```diff

deleted file mode 100644
index 797a753..0000000
--- a/packages/api/src/app/services/indexing/steps/get_repo_url.py
+++ /dev/null
@@ -1,155 +0,0 @@
    2       -"""Step: resolve the authenticated clone URL for ``owner/repo``.
    3       -
    4       -Private-repo support for the indexing pipeline. The public
    5       -``repo_url`` from :class:`IndexWorkflowInput` cannot clone a private
    6       -repo, so this step resolves the repo's GitHub installation and mints
    7       -an installation access token to build an authenticated clone URL via
    8       -:func:`app.services.setup._helpers.build_authenticated_clone_url`
    9       -(the same primitive the setup pipeline uses).
   10       -
   11       -Sequence:
   12       -
   13       -1. Look up the :class:`Installation` row by ``(user_id,
   14       -   ``account_login == repo_owner``)`` — the GitHub account that owns
   15       -   the repo. GitHub allows one installation per account per App, so
   16       -   the match is unique. A missing row is a final
   17       -   :class:`IndexInstallationNotFoundError` (no token can be minted).
   18       -2. Mint a fresh installation token via
   19       -   :func:`app.core.github_app.mint_installation_token`. Exceptions
   20       -   are wrapped in :class:`IndexInstallTokenMintError` (transient) so
   21       -   DBOS retries GitHub 5xx / network blips.
   22       -3. Build and return the authenticated clone URL.
   23       -
   24       -DBOS keys step registration on ``__name__``. Named ``getRepoUrl``
   25       -(camelCase) so it does not collide with the setup pipeline's
   26       -snake_case ``mint_installation_token_step``.
   27       -"""
   28       -
   29       -from __future__ import annotations
   30       -
   31       -import logging
   32       -
   33       -from dbos import DBOS
   34       -from sqlmodel import select
   35       -from sqlmodel.ext.asyncio.session import AsyncSession
   36       -
   37       -from app.core.db import async_session_maker
   38       -from app.core.github_app import mint_installation_token
   39       -from app.models.installation import Installation
   40       -from app.services.indexing.errors import (
   41       -    IndexInstallationNotFoundError,
   42       -    IndexInstallTokenMintError,
   43       -    _should_retry_index,
   44       -)
   45       -from app.services.setup._helpers import build_authenticated_clone_url
   46       -
   47       -log = logging.getLogger(__name__)
   48       -
   49       -
   50       -async def _find_github_installation_id(
   51       -    *,
   52       -    session: AsyncSession,
   53       -    user_id: str,
   54       -    account_login: str,
   55       -) -> int | None:
   56       -    """Return the GitHub-side installation id for the account, or ``None``.
   57       -
   58       -    Single ``SELECT github_installation_id FROM installations WHERE
   59       -    user_id = ? AND account_login = ?``. The ``user_id`` predicate is
   60       -    enforced at the DB layer; if a row matches the account login but
   61       -    belongs to a different user we get no hit.
   62       -    """
   63       -    stmt = select(Installation.github_installation_id).where(
   64       -        Installation.user_id == user_id,
   65       -        Installation.account_login == account_login,
   66       -    )
   67       -    result = await session.exec(stmt)
   68       -    return result.first()
   69       -
   70       -
   71       -@DBOS.step(
   72       -    retries_allowed=True,
   73       -    max_attempts=3,
   74       -    should_retry=_should_retry_index,
   75       -)
   76       -async def getRepoUrl(
   77       -    *,
   78       -    user_id: str,
   79       -    repo_owner: str,
   80       -    repo_name: str,
   81       -) -> str:
   82       -    """Resolve the authenticated clone URL for ``repo_owner/repo_name``.
   83       -
   84       -    Looks up the repo's installation by ``account_login == repo_owner``,
   85       -    mints a fresh installation token, and embeds it in the HTTPS clone
   86       -    URL. The caller passes the returned URL to
   87       -    :func:`gitCloneToSandbox` (``clone_url``), which uses it in place
   88       -    of the public ``repo_url`` from the input.
   89       -
   90       -    Returns:
   91       -        The authenticated clone URL as a plain ``str``
   92       -        (``https://x-access-token:<token>@github.com/{owner}/{name}.git``).
   93       -
   94       -    Raises:
   95       -        IndexInstallationNotFoundError: no :class:`Installation` row
   96       -            matches ``(user_id, repo_owner)``. Final — not retried.
   97       -        IndexInstallTokenMintError: the token mint failed. Transient —
   98       -            retried by DBOS up to ``max_attempts`` times.
   99       -    """
  100       -    try:
  101       -        async with async_session_maker() as session:
  102       -            github_installation_id = await _find_github_installation_id(
  103       -                session=session,
  104       -                user_id=user_id,
  105       -                account_login=repo_owner,
  106       -            )
  107       -    except Exception as exc:
  108       -        log.warning(
  109       -            "getRepoUrl: installation lookup failed user_id=%s owner=%s repo=%s cause=%s: %s",
  110       -            user_id,
  111       -            repo_owner,
  112       -            repo_name,
  113       -            type(exc).__name__,
  114       -            exc,
  115       -        )
  116       -        raise IndexInstallTokenMintError(
  117       -            cause=f"installation lookup failed: {type(exc).__name__}: {exc}"
  118       -        ) from exc
  119       -
  120       -    if github_installation_id is None:
  121       -        raise IndexInstallationNotFoundError(
  122       -            user_id=user_id,
  123       -            repo_owner=repo_owner,
  124       -            repo_name=repo_name,
  125       -        )
  126       -
  127       -    try:
  128       -        token = await mint_installation_token(github_installation_id)
  129       -    except Exception as exc:
  130       -        log.warning(
  131       -            "getRepoUrl: token mint failed installation_id=%s owner=%s repo=%s cause=%s: %s",
  132       -            github_installation_id,
  133       -            repo_owner,
  134       -            repo_name,
  135       -            type(exc).__name__,
  136       -            exc,
  137       -        )
  138       -        raise IndexInstallTokenMintError(cause=f"{type(exc).__name__}: {exc}") from exc
  139       -
  140       -    clone_url = build_authenticated_clone_url(
  141       -        install_token=token,
  142       -        owner=repo_owner,
  143       -        name=repo_name,
  144       -    )
  145       -
  146       -    log.info(
  147       -        "getRepoUrl: ok owner=%s repo=%s installation_id=%s",
  148       -        repo_owner,
  149       -        repo_name,
  150       -        github_installation_id,
  151       -    )
  152       -    return clone_url
  153       -
  154       -
  155       -__all__ = ["getRepoUrl"]
  156       -

```
