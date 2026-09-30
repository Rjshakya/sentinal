"""Repair durable handler: resolve owner ctx, then repair agent phase."""

from __future__ import annotations

import logging

from aws_durable_execution_sdk_python import durable_execution
from aws_durable_execution_sdk_python.config import StepConfig
from aws_durable_execution_sdk_python.context import DurableContext
from aws_durable_execution_sdk_python.retries import (
    RetryStrategyConfig,
    create_retry_strategy,
)

from app.workflows.durable.steps import (
    buildSandboxCtxForRun,
    getRepoByGithubId,
    getUserIdByInstallation,
    resolveActiveLlmCtx,
)
from app.workflows.durable.types import DurableRepairEvent

log = logging.getLogger(__name__)

RETRY_3 = StepConfig(
    retry_strategy=create_retry_strategy(RetryStrategyConfig(max_attempts=3))
)
RETRY_1 = StepConfig(
    retry_strategy=create_retry_strategy(RetryStrategyConfig(max_attempts=1))
)


@durable_execution
def repair_durable_handler(event: dict, ctx: DurableContext) -> dict:
    request = DurableRepairEvent.model_validate(event)
    payload = request.review_payload
    installation = payload.get("installation")
    installationId = (
        int(installation.get("id") or 0) if isinstance(installation, dict) else 0
    )
    repository = payload.get("repository")
    ghRepoId = int(repository.get("id") or 0) if isinstance(repository, dict) else 0

    userId = ctx.step(
        getUserIdByInstallation(installationId=installationId),
        name="get-user",
        config=RETRY_3,
    )
    if not userId:
        return {
            "posted": False,
            "reason": "unowned_installation",
            "delivery": request.delivery,
        }
    repo = ctx.step(
        getRepoByGithubId(ghRepoId=ghRepoId),
        name="get-repo",
        config=RETRY_3,
    )
    if repo is None:
        return {
            "posted": False,
            "reason": "repo_not_configured",
            "delivery": request.delivery,
        }
    llm = ctx.step(
        resolveActiveLlmCtx(userId=str(userId)),
        name="resolve-llm",
        config=RETRY_3,
    )
    sandbox = ctx.step(
        buildSandboxCtxForRun(
            input={
                "userId": str(userId),
                "repoId": str(repo["id"]),
                "repoName": str(repo.get("repoName") or repo.get("repo_name")),
            }
        ),
        name="build-sandbox",
        config=RETRY_1,
    )
    log.info(
        "repair: ctx resolved delivery=%s pr=%s commit=%s",
        request.delivery,
        request.pr_number,
        request.commit_id[:7],
    )
    return {
        "posted": False,
        "reason": "ctx-resolved",
        "delivery": request.delivery,
        "user_id": str(userId),
        "repo_id": str(repo["id"]),
        "llm_ctx": llm,
        "sandbox_ctx": sandbox,
        "phase": "ctx-resolved",
    }


__all__ = ["repair_durable_handler"]
