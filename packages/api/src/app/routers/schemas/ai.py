"""HTTP schemas for the repository configure endpoint.

``POST /ai/repo/setup`` is synchronous: it inserts one ``Repo`` row per
requested GitHub repo (skipping repos that already have a row) and
returns the per-repo outcome immediately. No sandbox, no workflow, no
polling.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class SetupRepo(BaseModel):
    """A single repo to configure."""

    id: int = Field(description="GitHub repo id (numeric).")
    owner: str = Field(description="GitHub repo owner (org or user).")
    name: str = Field(description="GitHub repo name.")
    installation_id: str = Field(
        description="Local Installation.id (UUID) owning the repo."
    )
    default_branch: Optional[str] = Field(
        default=None,
        description="Default branch as reported by GitHub at list time.",
    )


class SetupRequest(BaseModel):
    """Body of ``POST /ai/repo/setup``."""

    repos: list[SetupRepo] = Field(
        min_length=1,
        description="Non-empty list of repos to configure.",
    )


class ConfiguredRepo(BaseModel):
    """Per-repo outcome of a configure request."""

    github_repo_id: int = Field(description="GitHub repo id, echoed back.")
    repo_id: Optional[str] = Field(
        default=None,
        description="Local Repo.id when configured (or already existed).",
    )
    skipped: bool = Field(
        default=False,
        description="True when the repo already had a Repo row.",
    )
    error: Optional[str] = Field(
        default=None,
        description="Per-repo error when the row could not be created.",
    )


class ConfigureResponse(BaseModel):
    """Body of the ``POST /ai/repo/setup`` response."""

    repos: list[ConfiguredRepo]


__all__ = [
    "ConfiguredRepo",
    "ConfigureResponse",
    "SetupRepo",
    "SetupRequest",
]
