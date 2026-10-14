"""Durable entry point for pull_request opened (linear, guard-clauses).

Validates the event once, resolves ctx with early returns, then runs
the shared agent phase. No branching on trigger type — this handler
only serves opened.
"""

from __future__ import annotations

import logging

from aws_durable_execution_sdk_python import durable_execution
from aws_durable_execution_sdk_python.config import StepConfig
from aws_durable_execution_sdk_python.context import DurableContext
from aws_durable_execution_sdk_python.retries import (
    RetryStrategyConfig,
    create_retry_strategy,
)

from app.core.config import settings
from app.services.tracing.service import flushTraces
from app.workflows.durable.pipeline import AgentPhaseInput, runAgentPhase
from app.workflows.durable.steps import (
    buildSandboxCtxForRun,
    getRepoByGithubId,
    getUserIdByInstallation,
    parseOpenedPayload,
    resolveActiveLlmCtx,
)
from app.workflows.durable.types import OpenedDurableEvent, ReviewSkipped
from app.workflows.review_v2.types import ReviewWorkflowInput

log = logging.getLogger(__name__)

RETRY_3 = StepConfig(
    retry_strategy=create_retry_strategy(RetryStrategyConfig(max_attempts=3))
)
RETRY_1 = StepConfig(
    retry_strategy=create_retry_strategy(RetryStrategyConfig(max_attempts=1))
)


@durable_execution
def reviewOpenedHandler(event: dict, ctx: DurableContext) -> dict:
    request = OpenedDurableEvent.model_validate(event)
    try:
        return _reviewOpenedHandlerInner(request, ctx)
    finally:
        flushTraces()


def _reviewOpenedHandlerInner(request: OpenedDurableEvent, ctx: DurableContext) -> dict:

    opened = ctx.step(
        parseOpenedPayload(payload=request.payload),
        name="parse-opened",
        config=RETRY_1,
    )
    if opened is None:
        return ReviewSkipped(
            delivery=request.delivery, skip_reason="malformed_payload"
        ).model_dump(mode="json")

    installation = request.payload.get("installation")
    installationId = (
        int(installation.get("id") or 0)
        if isinstance(installation, dict)
        else 0
    )
    ghRepoId = int(opened["ghRepoId"])
    prNumber = int(opened["number"])

    userId = ctx.step(
        getUserIdByInstallation(installationId=installationId),
        name="get-user",
        config=RETRY_3,
    )
    if not userId:
        return ReviewSkipped(
            delivery=request.delivery, skip_reason="unowned_installation"
        ).model_dump(mode="json")

    repo = ctx.step(
        getRepoByGithubId(ghRepoId=ghRepoId),
        name="get-repo",
        config=RETRY_3,
    )
    if repo is None:
        return ReviewSkipped(
            delivery=request.delivery, skip_reason="repo_not_configured"
        ).model_dump(mode="json")

    repoId = str(repo["id"])
    headSha = str(opened["headSha"])
    baseSha = str(opened["baseSha"])

    llm = ctx.step(
        resolveActiveLlmCtx(userId=str(userId)),
        name="resolve-llm",
        config=RETRY_3,
    )
    sandbox = ctx.step(
        buildSandboxCtxForRun(
            input={
                "userId": str(userId),
                "repoId": repoId,
                "repoName": str(repo.get("repoName") or repo.get("repo_name")),
            }
        ),
        name="build-sandbox",
        config=RETRY_1,
    )

    log.info(
        "opened: ctx resolved delivery=%s repo=%s pr=%s head=%s",
        request.delivery,
        repoId,
        prNumber,
        headSha[:7],
    )

    workflowInput = ReviewWorkflowInput.model_validate(
        {
            "userId": userId,
            "ghRepoId": ghRepoId,
            "ghPrId": opened["ghPrId"],
            "prNumber": prNumber,
            "baseBranch": opened["baseBranch"],
            "defaultBranch": opened.get("defaultBranch"),
            "baseSha": baseSha,
            "headSha": headSha,
            "headBranch": opened["headBranch"],
            "author": opened["author"],
            "title": opened["title"],
            "body": opened.get("body") or "",
            "status": opened["status"],
            "trigger": "opened",
            "postToGithub": True,
            "githubInstallationId": installationId or None,
            "prSize": opened.get("prSize")
            or {"additions": 0, "deletions": 0, "changedFiles": 0},
            "diffBaseSha": None,
        }
    ).model_dump(mode="json")

    _ = settings
    return runAgentPhase(
        ctx,
        input=AgentPhaseInput(
            delivery=request.delivery,
            executionName=request.execution_name,
            userId=str(userId),
            repoId=repoId,
            repo=repo,
            workflowInput=workflowInput,
            llm=llm,
            sandbox=sandbox,
            installationId=installationId,
            prNumber=prNumber,
            headSha=headSha,
            baseSha=baseSha,
            diffBaseSha=None,
        ),
    )


__all__ = ["reviewOpenedHandler"]
