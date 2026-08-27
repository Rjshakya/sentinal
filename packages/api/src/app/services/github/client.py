"""Private GitHub client factory shared by the github sub-services.

Not part of the public surface — never import from outside
``app.services.github``. This is the single node that builds the
process-wide :class:`githubkit.auth.AppAuthStrategy` from settings and
derives installation-scoped clients from it. The App credentials are
validated at app startup, so no configuration gates live here.
"""

from __future__ import annotations

import base64
import binascii

from githubkit import GitHub
from githubkit.auth import AppAuthStrategy

from app.core.config import settings

github_app: GitHub[AppAuthStrategy] | None = None


def getGithubAppPrivateKey() -> str:
    """Return the App private key PEM.

    ``GITHUB_APP_PRIVATE_KEY`` carries the PEM, either base64-encoded
    or raw with literal ``\\n`` sequences.
    """
    raw = settings.github_app_private_key
    if raw is None:
        raise ValueError("No github_app_private_key")

    try:
        return base64.b64decode(raw, validate=True).decode("utf-8")
    except (binascii.Error, ValueError):
        return raw.replace("\\n", "\n")


def getAppGitHub() -> GitHub[AppAuthStrategy]:
    """Return the process-wide App-level client, built once from settings."""
    global github_app

    if github_app:
        return github_app

    private_key = getGithubAppPrivateKey()
    app = GitHub(
        AppAuthStrategy(
            app_id=settings.github_app_id,
            private_key=private_key,
            client_id=settings.github_app_client_id,
            client_secret=settings.github_app_client_secret,
        )
    )

    github_app = app
    return app


def getAuthenticatedGitHubClient(installationId: int) -> GitHub:
    """Derive an installation-scoped :class:`GitHub` from the App client.

    The returned client mints and caches its installation token under
    the hood.
    """
    app = getAppGitHub()
    return app.with_auth(app.auth.as_installation(installationId))


__all__ = ["getAppGitHub", "getAuthenticatedGitHubClient"]