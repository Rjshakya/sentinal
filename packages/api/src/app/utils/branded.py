from typing import NewType

UserId = NewType("UserId", str)
"""Branded WorkOS ``user_id`` the configuration belongs to."""

ApiKey = NewType("ApiKey", str)
"""Branded provider API key."""

BaseUrl = NewType("BaseUrl", str)
"""Branded provider / gateway base URL."""


RepoId = NewType("RepoId", str)
"""Branded local ``repos.id`` (UUID string) the sandbox belongs to."""

SandboxId = NewType("SandboxId", str)
"""Branded provider-assigned sandbox identifier; ``None`` until created."""

SanboxProviderApiKey = NewType("SanboxProviderApiKey", str)
"""Branded provider API key; resolved from settings by the factory when unset."""

InstallationId = NewType("InstallationId", int)
"""Branded GitHub App installation id (``github_installation_id``)."""

RepoOwner = NewType("RepoOwner", str)
"""Branded GitHub repository owner (user or org login)."""

RepoName = NewType("RepoName", str)
"""Branded GitHub repository name."""

PRNumber = NewType("PRNumber", int)
"""Branded GitHub pull request number."""

CommitId = NewType("CommitId", str)
"""Branded git commit SHA (the full hex string)."""

AccessToken = NewType("AccessToken", str)
"""Branded GitHub installation access token."""
