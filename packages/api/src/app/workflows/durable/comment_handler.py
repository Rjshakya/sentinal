"""Durable entry point for issue_comment review mentions (linear).

Validates the event once, resolves ctx with early returns, skips when
the head was already reviewed and posted, computes the incremental diff
base otherwise, then runs the shared agent phase. No opened logic lives
here.
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
    fetchLivePrState,
    getRepoByGithubId,
    getUserIdByInstallation,
    loadLastSuccessfulReview,
    parseCommentPayload,
    resolveActiveLlmCtx,
)
from app.workflows.durable.types import CommentDurableEvent, ReviewSkipped
from app.workflows.review_v2.types import ReviewWorkflowInput
from app.workflows.triggers.comment_payload import (
    effectiveDiffBase,
    isHeadAlreadyPosted,
)
from app.workflows.triggers.types import CommentTriggerInput, LastReviewSnapshot

log = logging.getLogger(__name__)

RETRY_3 = StepConfig(
    retry_strategy=create_retry_strategy(RetryStrategyConfig(max_attempts=3))
)
RETRY_1 = StepConfig(
    retry_strategy=create_retry_strategy(RetryStrategyConfig(max_attempts=1))
)


@durable_execution
def reviewCommentHandler(event: dict, ctx: DurableContext) -> dict:
    request = CommentDurableEvent.model_validate(event)
    try:
        return _reviewCommentHandlerInner(request, ctx)
    finally:
        flushTraces()


def _reviewCommentHandlerInner(
    request: CommentDurableEvent, ctx: DurableContext
) -> dict:

    triggerDict = ctx.step(
        parseCommentPayload(
            input={
                "payload": request.payload,
                "delivery": request.delivery,
                "appSlug": settings.github_app_slug,
            }
        ),
        name="parse-comment",
        config=RETRY_1,
    )
    if triggerDict is None:
        return ReviewSkipped(
            delivery=request.delivery, skip_reason="not_review_comment"
        ).model_dump(mode="json")

    trigger = CommentTriggerInput.model_validate(triggerDict)
    installationId = int(trigger.installationId)
    ghRepoId = int(trigger.ghRepoId)
    prNumber = int(trigger.prNumber)

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

    prState = ctx.step(
        fetchLivePrState(
            input={
                "userId": str(userId),
                "installationId": installationId,
                "owner": str(trigger.repoOwner),
                "repo": str(trigger.repoName),
                "prNumber": prNumber,
            }
        ),
        name="fetch-pr",
        config=RETRY_3,
    )
    if prState is None:
        return ReviewSkipped(
            delivery=request.delivery, skip_reason="pr_fetch_failed"
        ).model_dump(mode="json")

    headSha = str(prState["headSha"])
    baseSha = str(prState["baseSha"])

    lastDict = ctx.step(
        loadLastSuccessfulReview(
            input={"repoId": str(repo["id"]), "prNumber": prNumber}
        ),
        name="load-last",
        config=RETRY_3,
    )
    lastReview = LastReviewSnapshot.model_validate(lastDict) if lastDict else None
    if isHeadAlreadyPosted(apiHeadSha=headSha, lastReview=lastReview):
        log.info(
            "comment: head already posted delivery=%s repo=%s pr=%s head=%s",
            request.delivery,
            repo.get("id"),
            prNumber,
            headSha[:7],
        )
        return ReviewSkipped(
            delivery=request.delivery, skip_reason="head_already_posted"
        ).model_dump(mode="json")
    diffBase = effectiveDiffBase(
        apiBaseSha=baseSha, apiHeadSha=headSha, lastReview=lastReview
    )
    diffBaseSha = str(diffBase) if diffBase is not None else None

    repoId = str(repo["id"])
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
        "comment: ctx resolved delivery=%s repo=%s pr=%s head=%s diff_base=%s",
        request.delivery,
        repoId,
        prNumber,
        headSha[:7],
        (diffBaseSha[:7] if diffBaseSha else None),
    )

    state = str(prState.get("state"))
    merged = bool(prState.get("merged"))
    status = "MERGED" if (state == "closed" and merged) else ("CLOSED" if state == "closed" else "OPEN")

    workflowInput = ReviewWorkflowInput.model_validate(
        {
            "userId": userId,
            "ghRepoId": ghRepoId,
            "ghPrId": prState.get("ghPrId"),
            "prNumber": prNumber,
            "baseBranch": prState.get("baseBranch"),
            "defaultBranch": triggerDict.get("defaultBranch") or repo.get("defaultBranch"),
            "baseSha": baseSha,
            "headSha": headSha,
            "headBranch": prState.get("headBranch"),
            "author": prState.get("author"),
            "title": prState.get("title"),
            "body": prState.get("body") or "",
            "status": status,
            "trigger": "comment",
            "postToGithub": True,
            "githubInstallationId": installationId or None,
            "prSize": {
                "additions": int(prState.get("additions") or 0),
                "deletions": int(prState.get("deletions") or 0),
                "changedFiles": int(prState.get("changedFiles") or 0),
            },
            "diffBaseSha": diffBaseSha,
        }
    ).model_dump(mode="json")

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
            diffBaseSha=diffBaseSha,
        ),
    )


__all__ = ["reviewCommentHandler"]
