"""AI routes: the synchronous setup-agent endpoint.

The only live route is ``POST /ai/repo/setup``. The caller blocks on
the agent's structured response because there is nothing useful to ack
before the install lands.

All handlers are provider-agnostic: they build a
:class:`SandboxSpec` from current settings (via
:func:`build_default_spec`) and hand it to the underlying service. The
service never sees a concrete provider.

The setup endpoint is a thin adapter over
:mod:`app.services.agent.setup_pipeline`. The router owns the
sandbox lifecycle (``create`` / ``kill``) and the per-repo
persistence (``Sandbox`` row on create + kill, ``reposetupresult``
row on completion); the pipeline owns the step sequence and the
``Result`` composition. No business logic lives in this file.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import cast

from fastapi import APIRouter, HTTPException, Request
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.core.db import async_session_maker
from app.core.llm import LLMProviderStr
from app.core.result import Err, Ok, Result
from app.core.sandbox import BaseSandbox, build_default_spec, create_sandbox
from app.core.sandbox.e2b import E2BSandboxSpec
from app.models.enums import (
    SandboxState,
    SetupRunStatus,
)
from app.models.installation import Installation
from app.models.repo import Repo as RepoModel
from app.models.repo_setup_result import RepoSetupResult as RepoSetupResultModel
from app.models.sandbox import Sandbox as SandboxModel
from app.repositories import make_repo
from app.schemas.setup import RepoSetupResult, SetupAck, SetupRepo, SetupRequest
from app.services.agent.models import SetupResult
from app.services.agent.setup_errors import (
    SetupAgentCrashed,
    SetupPipelineError,
)
from app.services.agent.setup_pipeline import (
    E2BInstallTokenMinter,
    SetupAgentRunner,
    flatten_pipeline_error_to_setup_result,
    run_setup_pipeline,
)
from app.utils.util import uuidToStr

log = logging.getLogger(__name__)

router = APIRouter(prefix="/ai", tags=["ai"])


# --------------------------------------------------------------------------- #
# POST /ai/repo/setup — synchronous setup-agent endpoint                      #
# --------------------------------------------------------------------------- #


@router.post("/repo/setup", response_model=SetupAck)
async def setup_repos(
    payload: SetupRequest,
    request: Request,
) -> SetupAck:
    """Synchronously run the setup agent for every repo in the request.

    Each repo is processed by :func:`_setup_one_repo`, which owns
    the sandbox lifecycle (``create`` / ``kill``) and delegates the
    actual work to :func:`app.services.agent.setup_pipeline.run_setup_pipeline`.
    The handler does not raise on a per-repo failure — every repo
    is attempted, and a per-repo failure is encoded in the
    corresponding :class:`RepoSetupResult.setup` (``ok=False``).

    The endpoint is synchronous: the caller blocks on the agent's
    structured response. There is nothing useful to ack before the
    install lands.

    Preconditions:

    - The LLM must be configured (``LLM_BASE_URL``, ``LLM_MODEL`` and
      an API key). Otherwise we 503.
    - The active sandbox provider must be configured
      (``E2B_API_KEY`` for the default provider). The
      :func:`build_default_spec` factory raises if the key is missing.
    """
    if not payload.repos:
        raise HTTPException(
            status_code=400,
            detail="`repos` must contain at least one item",
        )

    if not settings.llm_configured:
        raise HTTPException(
            status_code=503,
            detail=(
                "Setup LLM is not configured. Set LLM_BASE_URL, LLM_MODEL, "
                "and LLM_API_KEY (or OPENAI_API_KEY) in the environment."
            ),
        )

    user_id: str = request.state.user_id
    spec = build_default_spec("e2b")

    results: list[RepoSetupResult] = []

    for input in payload.repos:
        result = await _setup_repo(user_id=user_id, input=input, spec=spec)
        if result is not None:
            results.append(result)

    return SetupAck(results=results)


async def _setup_repo(
    *,
    user_id: str,
    input: SetupRepo,
    spec: E2BSandboxSpec,
) -> RepoSetupResult | None:
    """Thin Ring-3 adapter for a single repo.

    Owns the sandbox lifecycle (``create`` / ``kill``) and the
    per-repo persistence (``Sandbox`` row on create + kill,
    ``reposetupresult`` row on completion). Delegates the actual
    setup work to :func:`run_setup_pipeline`. Never raises —
    every failure mode is encoded in the returned
    :class:`RepoSetupResult.setup` (an ``ok=False`` :class:`SetupResult`).
    """
    async with async_session_maker() as session:
        try:
            sandbox_repo = make_repo(SandboxModel, session)
            repo_table_repo = make_repo(RepoModel, session)
            repo_setup_result_table_repo = make_repo(RepoSetupResultModel, session)

            # upsert repo record

            repo_record = await repo_table_repo.find_by_field(
                RepoModel.github_repo_id, input.id
            )

            if repo_record is None:
                repo_record = await repo_table_repo.add(
                    RepoModel(
                        id=uuidToStr(),
                        user_id=user_id,
                        github_repo_id=input.id,
                        repo_name=input.name,
                        repo_owner=input.owner,
                        clone_url=f"https://github.com/{input.owner}/{input.name}.git",
                    )
                )
                await session.commit()
                await session.refresh(repo_record)

            # initialize sandbox
            sandbox: BaseSandbox = create_sandbox(
                spec=spec,
                user_id=user_id,
                repo_id=repo_record.id,
                sandbox_name=f"{input.owner}-{input.name}-setup",
            )

            await sandbox.create()

            # Persist sandbox record
            sandbox_record = await sandbox_repo.add(
                SandboxModel(
                    id=sandbox.id,
                    user_id=user_id,
                    repo_id=repo_record.id,
                    sandbox_name=sandbox.sandbox_name,
                    state=SandboxState.STARTED,
                    provider_id="e2b",
                )
            )

            await session.commit()
            await session.refresh(sandbox_record)

            started_at = datetime.now()

            # Run Main Agent loop
            result = await _run_setup_agent_pipeline(
                user_id=user_id,
                input=input,
                sandbox=sandbox,
                session=session,
            )

            completed_at = datetime.now()

            # save setup result
            if isinstance(result, Ok):
                setup_result = result.value
                payload = create_save_repo_setup_result_payload(
                    repo_id=repo_record.id,
                    user_id=user_id,
                    sandbox_id=sandbox_record.id,
                    llm_provider=settings.llm_provider,
                    llm_model=settings.llm_model,
                    pipeline_result=setup_result,
                    started_at=started_at,
                    completed_at=completed_at,
                )

                await repo_setup_result_table_repo.add(payload)

            # cleanify
            stop_sandbox = await sandbox.stop()
            await sandbox_repo.update_by_field(
                SandboxModel.id,
                sandbox_record.id,
                state=SandboxState.STOPPED,
                stopped_at=stop_sandbox.stopped_at or datetime.now(UTC),
            )

            await session.commit()

            if isinstance(result, Ok):
                return RepoSetupResult(
                    repo_id=repo_record.id,
                    github_repo_id=input.id,
                    setup=result.value,
                )

            return RepoSetupResult(
                repo_id=repo_record.id,
                github_repo_id=input.id,
                setup=flatten_pipeline_error_to_setup_result(result.error),
            )

        except Exception as e:
            log.error(e)


async def _run_setup_agent_pipeline(
    *,
    user_id: str,
    input: SetupRepo,
    sandbox: BaseSandbox,
    session: AsyncSession,
) -> Result[SetupResult, SetupPipelineError]:
    """Create the sandbox (persisting the :class:`Sandbox` row on
    success) and run the setup pipeline. Returns the ``Result``,
    the sandbox id (when the sandbox was actually created), and
    the host-clock ``started_at``. Never raises.
    """

    try:
        installation_repo = make_repo(Installation, session)

        result = await run_setup_pipeline(
            user_id=user_id,
            input=input,
            installation_repo=installation_repo,
            install_token_minter=E2BInstallTokenMinter(),
            sandbox=sandbox,
            setup_agent_runner=SetupAgentRunner(
                llm_provider=cast(LLMProviderStr, settings.llm_provider),
                llm_base_url=settings.llm_base_url or None,
                llm_api_key=settings.llm_api_key,
                llm_model=settings.llm_model,
            ),
        )

        return result
    except Exception as e:
        log.error(e)
        return Err(SetupAgentCrashed(cause=str(e)))


# --------------------------------------------------------------------------- #
# helpers                                                                      #
# --------------------------------------------------------------------------- #


def create_save_repo_setup_result_payload(
    *,
    repo_id: str,
    user_id: str,
    sandbox_id: str | None,
    started_at: datetime,
    completed_at: datetime,
    llm_provider: str,
    llm_model: str,
    pipeline_result: SetupResult,
) -> RepoSetupResultModel:
    """Pure: build the row payload from the pipeline outcome."""

    configured_repo = pipeline_result

    return RepoSetupResultModel(
        repo_id=repo_id,
        user_id=user_id,
        status=SetupRunStatus.SUCCEEDED,
        ok=configured_repo.ok,
        ecosystem=configured_repo.ecosystem,
        manager=configured_repo.manager,
        install_cmd=configured_repo.install_cmd,
        bootstrapped_tools=configured_repo.bootstrapped_tools,
        duration_s=int((completed_at - started_at).total_seconds()),
        notes=configured_repo.notes,
        llm_provider=llm_provider,
        llm_model=llm_model,
        sandbox_id=sandbox_id,
    )
