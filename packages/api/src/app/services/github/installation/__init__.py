"""Installation sub-service: GitHub App install flow + local state.

Public surface:

- :func:`createInstallationCtx` — ctx constructor.
- :func:`getInstallUrl` — signed install URL for the browser.
- :func:`getInstallation` — installation details from the GitHub API.
- :func:`listInstallations` — the user's local installation rows.
- :func:`forgetInstallation` — local forget (delete rows).

Error contract: **no function raises.** Failures are returned as
:class:`GitHubInstallationError` values; callers discriminate with
``isinstance``.
"""

from app.services.github.installation.errors import GitHubInstallationError
from app.services.github.installation.service import (
    createInstallationCtx,
    forgetInstallation,
    getInstallUrl,
    getInstallation,
    listInstallations,
)
from app.services.github.installation.types import (
    InstallationCtx,
    InstallationDetails,
    InstallUrl,
)

__all__ = [
    "GitHubInstallationError",
    "InstallationCtx",
    "InstallationDetails",
    "InstallUrl",
    "createInstallationCtx",
    "forgetInstallation",
    "getInstallUrl",
    "getInstallation",
    "listInstallations",
]