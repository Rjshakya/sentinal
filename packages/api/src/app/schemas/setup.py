"""HTTP schemas for ``POST /ai/repo/setup``.

The endpoint accepts a list of repos (mirroring
:class:`app.schemas.indexing.IndexingRequest`'s shape) and returns
a per-repo :class:`app.services.agent.models.SetupResult`. The
endpoint is fully synchronous — the handler runs the setup agent to
completion before responding.

The actual work lives in
:mod:`app.services.agent.setup_pipeline`; this module is the
HTTP-shape contract only.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.services.agent.models import SetupResult


class SetupRepo(BaseModel):
    """A single repo to set up.

    ``id`` is the GitHub repo id (numeric, coerced to int in the
    handler). ``owner`` and ``name`` are needed to construct the
    authenticated clone URL inside the sandbox. ``installation_id`` is
    the local :class:`app.models.installation.Installation` row's
    primary key, used to look up the GitHub installation id and mint
    a fresh install token for the clone.
    """

    id: int = Field(
        description="GitHub repo id (numeric).",
    )
    owner: str = Field(
        description="GitHub repo owner (org or user).",
    )
    name: str = Field(
        description="GitHub repo name.",
    )
    installation_id: str = Field(
        description="Local Installation.id (UUID) used to mint the "
        "install token for the clone.",
    )


class SetupRequest(BaseModel):
    """Body of ``POST /ai/repo/setup``."""

    repos: list[SetupRepo] = Field(
        min_length=1,
        description="Non-empty list of repos to set up. The handler "
        "validates the request and 400s on an empty list.",
    )


class RepoSetupResult(BaseModel):
    """Per-repo entry in :class:`SetupAck.results`."""

    repo_id: str | None = Field(
        description="Local Repo.id (UUID). None when the upsert failed.",
    )
    github_repo_id: int = Field(
        description="GitHub repo id, echoed back from the request.",
    )
    setup: SetupResult = Field(
        description="Structured output of the setup agent.",
    )


class SetupAck(BaseModel):
    """Response of ``POST /ai/repo/setup``.

    One :class:`RepoSetupResult` per repo in the request, in the same
    order. The handler does not short-circuit on failure — every repo
    is attempted, and partial success is reflected by a mix of
    ``ok=true`` and ``ok=false`` entries.
    """

    results: list[RepoSetupResult]


__all__: list[str] = [
    "RepoSetupResult",
    "SetupAck",
    "SetupRepo",
    "SetupRequest",
]
