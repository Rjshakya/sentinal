"""Shared edge helpers for the workflow triggers.

Generic run-environment resolvers used by every trigger adapter in this
package — no workflow knowledge lives here. Each helper takes the
caller's :class:`AsyncSession` (I/O at the edge, per the service
conventions); nothing here opens its own session.

Copied from :mod:`app.workflows.review.triggers` (which remains untouched
until the step-2 deletion); this module is the canonical home going
forward.
"""

from __future__ import annotations

import logging
from typing import cast

from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.models.repo import Repo
from app.repositories.installation import InstallationRepository
from app.repositories.repo import RepoRepository
from app.services.llm import (
    LLMContextError,
    LLMCtx,
    createDefaultLLMContext,
    createUserLLMContext,
)
from app.services.sandbox.service import (
    DEFAULT_ROOT_PATH,
    createSandboxCtx,
    getDefaulSandboxName,
)
from app.services.sandbox.types import ProviderId, SanboxProviderApiKey, SandboxCtx
from app.utils.branded import RepoId, UserId

log = logging.getLogger(__name__)


async def resolveLlmCtx(session: AsyncSession, *, userId: str) -> LLMCtx:
    """Resolve the run's LLM context: the user's stored row, else settings."""
    result = await createUserLLMContext(session, UserId(userId))
    if isinstance(result, LLMContextError):
        log.info(
            "triggers: no user llm config, falling back to settings: user_id=%s",
            userId,
        )
        return createDefaultLLMContext()
    return result


def buildSandboxCtx(*, userId: str, repoId: str, repoName: str) -> SandboxCtx:
    """Assemble the run's sandbox context from settings-driven defaults."""
    provider = cast(ProviderId, settings.sandbox_provider)
    api_key = settings.e2b_api_key if provider == "e2b" else settings.daytona_api_key
    return createSandboxCtx(
        userId=UserId(userId),
        repoId=RepoId(repoId),
        repoName=repoName,
        providerId=provider,
        apiKey=SanboxProviderApiKey(api_key),
        sandboxName=getDefaulSandboxName(repoName),
        rootPath=DEFAULT_ROOT_PATH[provider],
    )


def handleOpencodeLLMCtx(llm_ctx: LLMCtx, commitId: str) -> LLMCtx:
    """Tag opencode-gateway LLM contexts with the run's session header."""
    ctx = llm_ctx
    if ctx is not None and "opencode" in str(ctx.baseUrl):
        ctx.defaultHeaders = {"x-opencode-session": f"session-{commitId[:6]}"}

    return ctx


async def getUserIdFromInstallation(
    session: AsyncSession, *, githubInstallationId: int
) -> str | None:
    """Return the WorkOS ``user_id`` that owns the installation, or ``None``."""
    row = await InstallationRepository(session=session).find_by_github_installation_id(
        githubInstallationId
    )
    return row.user_id if row is not None else None


async def getRepoRecord(session: AsyncSession, *, ghRepoId: int) -> Repo | None:
    """Return the local :class:`Repo` row for a GitHub repo id, or ``None``."""
    return await RepoRepository(session=session).find_by_github_repo_id(ghRepoId)


__all__ = [
    "buildSandboxCtx",
    "getRepoRecord",
    "getUserIdFromInstallation",
    "handleOpencodeLLMCtx",
    "resolveLlmCtx",
]
