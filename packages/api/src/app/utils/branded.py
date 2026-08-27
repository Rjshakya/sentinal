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
