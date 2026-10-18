"""Ctx-resolution steps: installation -> user, repo, LLM, sandbox.

Each step validates its input model first, runs one DB/settings lookup,
and returns ``model_dump(mode="json")``. Every step is a native
``async def``; the worker runs inline.
"""

from __future__ import annotations

import logging
from typing import cast

from async_durable_execution import durable_callable
from langfuse import observe
from pydantic import BaseModel, ConfigDict

from app.core.config import settings
from app.core.db import async_session_maker
from app.repositories.installation import InstallationRepository
from app.repositories.repo import RepoRepository
from app.services.llm.service import createDefaultLLMContext, createUserLLMContext
from app.services.llm.types import LLMCtx
from app.services.sandbox.service import (
    DEFAULT_ROOT_PATH,
    createSandboxCtx,
    getDefaulSandboxName,
)
from app.services.sandbox.types import ProviderId, SanboxProviderApiKey
from app.utils.branded import RepoId, UserId
from app.workflows.review_v2.types import RepoSnapshot

log = logging.getLogger(__name__)


class RepoSnapshotOutput(RepoSnapshot):
    """Alias so the step return type reads as an output model."""

    model_config = ConfigDict(frozen=True)


@durable_callable
@observe(name="get-user-by-installation", capture_input=False, capture_output=False)
async def getUserIdByInstallation(*, installationId: int) -> str | None:
    """Return the WorkOS user_id owning a GitHub installation, else None."""
    async with async_session_maker() as session:
        row = await InstallationRepository(
            session=session
        ).find_by_github_installation_id(installationId)
        if row is None:
            return None
        return str(row.user_id)


@durable_callable
@observe(name="get-repo-by-github-id", capture_input=False, capture_output=False)
async def getRepoByGithubId(*, ghRepoId: int) -> dict | None:
    """Return the local repo snapshot for a GitHub repo id, else None."""
    async with async_session_maker() as session:
        row = await RepoRepository(session=session).find_by_github_repo_id(ghRepoId)
        if row is None:
            return None
        return RepoSnapshotOutput(
            id=RepoId(row.id),
            repoOwner=row.repo_owner,  # type: ignore[arg-type]
            repoName=row.repo_name,  # type: ignore[arg-type]
            defaultBranch=row.default_branch,
        ).model_dump(mode="json")


@durable_callable
@observe(name="resolve-llm-ctx", capture_input=False, capture_output=False)
async def resolveActiveLlmCtx(*, userId: str) -> dict:
    """Return the run LLM ctx: user's stored row, else settings default."""
    async with async_session_maker() as session:
        result = await createUserLLMContext(session, UserId(userId))
        if isinstance(result, LLMCtx):
            return result.model_dump(mode="json")
        log.info(
            "resolveActiveLlmCtx: no user config, using settings: user_id=%s",
            userId,
        )
        return createDefaultLLMContext().model_dump(mode="json")


class SandboxCtxInput(BaseModel):
    """Validated input for building the run sandbox ctx (pure, no I/O)."""

    model_config = ConfigDict(frozen=True)

    userId: UserId
    repoId: RepoId
    repoName: str


@durable_callable
@observe(name="build-sandbox-ctx", capture_input=False, capture_output=False)
async def buildSandboxCtxForRun(*, input: dict) -> dict:
    """Assemble the settings-driven sandbox ctx (pure, no I/O)."""
    request = SandboxCtxInput.model_validate(input)
    provider = cast(ProviderId, settings.sandbox_provider)
    api_key = settings.e2b_api_key if provider == "e2b" else settings.daytona_api_key
    return createSandboxCtx(
        userId=request.userId,
        repoId=request.repoId,
        repoName=request.repoName,
        providerId=provider,
        apiKey=SanboxProviderApiKey(api_key),
        sandboxName=getDefaulSandboxName(request.repoName),
        rootPath=DEFAULT_ROOT_PATH[provider],
    ).model_dump(mode="json")


__all__ = [
    "buildSandboxCtxForRun",
    "getRepoByGithubId",
    "getUserIdByInstallation",
    "resolveActiveLlmCtx",
]
