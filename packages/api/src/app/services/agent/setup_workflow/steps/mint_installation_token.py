"""Step 2: mint a fresh GitHub installation access token.

The token is short-lived (E2B caches it for us via the App's
:class:`githubkit.auth.AppAuthStrategy`, but the API call here is
explicit so the workflow captures a token for the clone step and
for the sandbox's ``GITHUB_TOKEN`` env var).
"""

from __future__ import annotations

import logging

from dbos import DBOS

from app.core.github_app import mint_installation_token
from app.services.agent.setup_workflow.errors import InstallTokenMintError

log = logging.getLogger(__name__)


def _should_retry_setup(exc: BaseException) -> bool:
    from app.services.agent.setup_workflow.errors import TransientSetupError

    return isinstance(exc, TransientSetupError)


@DBOS.step(
    retries_allowed=True,
    max_attempts=3,
    should_retry=_should_retry_setup,
)
async def mint_installation_token_step(*, github_installation_id: int) -> str:
    """Mint a fresh installation access token for ``github_installation_id``.

    Wraps :func:`app.core.github_app.mint_installation_token` and
    converts any exception into :class:`InstallTokenMintError` so the
    workflow's typed-error boundary stays clean. Retried up to
    ``max_attempts`` times on transient SDK failures (network blips,
    GitHub 5xx, etc.).

    Returns:
        The fresh installation access token as a plain ``str``. The
        caller is responsible for embedding it in the clone URL via
        :func:`app.services.agent.setup_workflow._helpers.build_authenticated_clone_url`.

    Raises:
        InstallTokenMintError: the underlying
            :func:`mint_installation_token` raised. Retried by DBOS
            on :class:`TransientSetupError`; final on persistent
            failure.
    """
    try:
        token = await mint_installation_token(github_installation_id)
    except Exception as exc:
        log.exception(
            "mint_installation_token failed: installation_id=%s",
            github_installation_id,
        )
        raise InstallTokenMintError(
            cause=f"{type(exc).__name__}: {exc}"
        ) from exc
    return token


__all__ = ["mint_installation_token_step"]

