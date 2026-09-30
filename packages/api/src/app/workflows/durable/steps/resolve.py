"""Ctx-resolution steps: installation -> user, repo, LLM, sandbox.

Each step validates its input model first, runs one DB/settings lookup,
and returns ``model_dump(mode="json")``. No lazy imports, no private
async helpers — the async worker is inline via ``asyncio.run``.
"""

from __future__ import annotations

import asyncio
import logging
from typing import cast

from aws_durable_execution_sdk_python import durable_step
from aws_durable_execution_sdk_python.types import StepContext
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
from app.services.sandbox.types import ProviderId, SanboxProviderApiKey, SandboxCtx
from app.utils.branded import RepoId, UserId
from app.workflows.review_v2.types import RepoSnapshot

log = logging.getLogger(__name__)


class RepoSnapshotOutput(RepoSnapshot):
    """Alias so the step return type reads as an output model."""

    model_config = ConfigDict(frozen=True)


@durable_step
def getUserIdByInstallation(
    _ctx: StepContext, *, installationId: int
) -> str | None:
    """Return the WorkOS user_id owning a GitHub installation, else None."""

    async def run() -> str | None:
        async with async_session_maker() as session:
            row = await InstallationRepository(
                session=session
            ).find_by_github_installation_id(installationId)
            if row is None:
                return None
            return str(row.user_id)

    return asyncio.run(run())


@durable_step
def getRepoByGithubId(_ctx: StepContext, *, ghRepoId: int) -> dict | None:
    """Return the local repo snapshot for a GitHub repo id, else None."""

    async def run() -> dict | None:
        async with async_session_maker() as session:
            row = await RepoRepository(session=session).find_by_github_repo_id(
                ghRepoId
            )
            if row is None:
                return None
            return RepoSnapshotOutput(
                id=RepoId(row.id),
                repoOwner=row.repo_owner,  # type: ignore[arg-type]
                repoName=row.repo_name,  # type: ignore[arg-type]
                defaultBranch=row.default_branch,
            ).model_dump(mode="json")

    return asyncio.run(run())


@durable_step
def resolveActiveLlmCtx(_ctx: StepContext, *, userId: str) -> dict:
    """Return the run LLM ctx: user's stored row, else settings default."""

    async def run() -> dict:
        async with async_session_maker() as session:
            result = await createUserLLMContext(session, UserId(userId))
            if isinstance(result, LLMCtx):
                return result.model_dump(mode="json")
            log.info(
                "resolveActiveLlmCtx: no user config, using settings: user_id=%s",
                userId,
            )
            return createDefaultLLMContext().model_dump(mode="json")

    return asyncio.run(run())


class SandboxCtxInput(BaseModel):
    """Validated input for building the run sandbox ctx (pure, no I/O)."""

    model_config = ConfigDict(frozen=True)

    userId: UserId
    repoId: RepoId
    repoName: str


@durable_step
def buildSandboxCtxForRun(_ctx: StepContext, *, input: dict) -> dict:
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
