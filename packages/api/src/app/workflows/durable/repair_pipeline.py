"""Shared repair phase: load unpublished review -> sandbox -> repair -> save.

Called by the repair durable handler. Linear ``ctx.step`` calls only —
no closures, no wrappers. Ctx resolution (load + LLM + sandbox) returns
early with ``RepairSkipped``; the agent phase is wrapped in
try/except that issues one plain destroy step and returns
``RepairFailed``. Imports on top.
"""

from __future__ import annotations

import logging

from aws_durable_execution_sdk_python.config import StepConfig
from aws_durable_execution_sdk_python.context import DurableContext
from aws_durable_execution_sdk_python.retries import (
    RetryStrategyConfig,
    create_retry_strategy,
)
from pydantic import BaseModel, ConfigDict

from app.workflows.durable.steps import (
    buildSandboxCtxForRun,
    clonePrHead,
    createEphemeralSandbox,
    deleteClonedRepo,
    destroySandbox,
    fetchPrDiff,
    loadUnpublishedReview,
    resolveActiveLlmCtx,
    runRepairAgent,
    savePublishOutcome,
    splitPrDiff,
)
from app.workflows.durable.types import (
    RepairCompleted,
    RepairFailed,
    RepairSkipped,
    UnpublishedReview,
)
from app.workflows.review_v2.steps._helpers import getReviewDiffDirPath
from app.workflows.review_v2.types import ReviewWorkflowInput

log = logging.getLogger(__name__)

RETRY_3 = StepConfig(
    retry_strategy=create_retry_strategy(RetryStrategyConfig(max_attempts=3))
)
RETRY_1 = StepConfig(
    retry_strategy=create_retry_strategy(RetryStrategyConfig(max_attempts=1))
)


class RepairPhaseInput(BaseModel):
    """Everything the repair phase needs (already validated)."""

    model_config = ConfigDict(frozen=True)

    delivery: str
    executionName: str
    commitId: str


def runRepairPhase(ctx: DurableContext, *, input: RepairPhaseInput) -> dict:
    unpublishedDict = ctx.step(
        loadUnpublishedReview(commitId=input.commitId),
        name="load-unpublished",
        config=RETRY_3,
    )
    if unpublishedDict is None:
        return RepairSkipped(
            delivery=input.delivery, skip_reason="nothing_to_publish"
        ).model_dump(mode="json")

    unpublished = UnpublishedReview.model_validate(unpublishedDict)
    userId = str(unpublished.userId)
    repoId = str(unpublished.repoId)
    repoName = str(unpublished.repoName)
    repoOwner = str(unpublished.repoOwner)
    prNumber = int(unpublished.prNumber)
    headSha = str(unpublished.commitId)
    baseSha = str(unpublished.baseSha or unpublished.commitId)
    installationId = int(unpublished.installationId)

    llm = ctx.step(
        resolveActiveLlmCtx(userId=userId),
        name="resolve-llm",
        config=RETRY_3,
    )
    sandbox = ctx.step(
        buildSandboxCtxForRun(
            input={"userId": userId, "repoId": repoId, "repoName": repoName}
        ),
        name="build-sandbox",
        config=RETRY_1,
    )

    log.info(
        "repair: ctx resolved delivery=%s pr=%s commit=%s comments=%d",
        input.delivery,
        prNumber,
        headSha[:7],
        len(unpublished.comments),
    )

    # Carrier for the reused review sandbox steps (clone/diff/split only
    # read userId/prNumber/headSha/baseSha/installation).
    workflowInput = ReviewWorkflowInput.model_validate(
        {
            "userId": userId,
            "ghRepoId": 0,
            "ghPrId": 0,
            "prNumber": prNumber,
            "baseBranch": "",
            "defaultBranch": None,
            "baseSha": baseSha,
            "headSha": headSha,
            "headBranch": "",
            "author": "",
            "title": "",
            "body": "",
            "status": "OPEN",
            "trigger": "repair",
            "postToGithub": False,
            "githubInstallationId": installationId or None,
            "prSize": {"additions": 0, "deletions": 0, "changedFiles": 0},
            "diffBaseSha": None,
        }
    ).model_dump(mode="json")

    sandboxActive: dict = dict(sandbox)
    try:
        sandboxActive = ctx.step(
            createEphemeralSandbox(sandbox=sandbox),
            name="create-sandbox",
            config=RETRY_3,
        )
        ctx.step(
            clonePrHead(
                input={
                    "sandbox": sandboxActive,
                    "workflowInput": workflowInput,
                    "repoId": repoId,
                    "repoOwner": repoOwner,
                    "repoName": repoName,
                    "installationId": installationId,
                }
            ),
            name="clone",
            config=RETRY_3,
        )
        ctx.step(
            fetchPrDiff(
                input={
                    "sandbox": sandboxActive,
                    "workflowInput": workflowInput,
                    "repoId": repoId,
                    "repoName": repoName,
                }
            ),
            name="fetch-diff",
            config=RETRY_3,
        )
        ctx.step(
            splitPrDiff(
                input={
                    "sandbox": sandboxActive,
                    "workflowInput": workflowInput,
                    "repoId": repoId,
                }
            ),
            name="split-diff",
            config=RETRY_3,
        )
        diffDir = getReviewDiffDirPath(prNumber, headSha)
        ctx.step(
            deleteClonedRepo(
                input={"sandbox": sandboxActive, "repoName": repoName}
            ),
            name="delete-repo",
            config=RETRY_1,
        )
        publishedDict = ctx.step(
            runRepairAgent(
                input={
                    "llm": llm,
                    "unpublished": unpublishedDict,
                    "sandbox": sandboxActive,
                    "diffDir": diffDir,
                }
            ),
            name="run-repair-agent",
            config=RETRY_3,
        )
        if publishedDict is None:
            ctx.step(
                destroySandbox(sandbox=sandboxActive),
                name="kill-sandbox-done",
                config=RETRY_1,
            )
            return RepairCompleted(
                delivery=input.delivery,
                execution_name=input.executionName,
                review_id=str(unpublished.reviewId),
                pr_number=prNumber,
                commit_id=headSha,
                posted=False,
                posted_count=0,
                dropped_count=len(unpublished.comments),
                attempts=0,
            ).model_dump(mode="json")

        ctx.step(
            savePublishOutcome(
                input={"unpublished": unpublishedDict, "published": publishedDict}
            ),
            name="save-published",
            config=RETRY_3,
        )
        ctx.step(
            destroySandbox(sandbox=sandboxActive),
            name="kill-sandbox-done",
            config=RETRY_1,
        )
        posted = publishedDict.get("postedComments") or []
        left = publishedDict.get("leftComments") or []
        log.info(
            "repair: complete delivery=%s pr=%s review=%s posted=%d left=%d",
            input.delivery,
            prNumber,
            publishedDict.get("githubReviewId"),
            len(posted),
            len(left),
        )
        return RepairCompleted(
            delivery=input.delivery,
            execution_name=input.executionName,
            review_id=str(unpublished.reviewId),
            pr_number=prNumber,
            commit_id=headSha,
            posted=True,
            github_review_id=int(publishedDict["githubReviewId"]),
            posted_count=len(posted),
            dropped_count=len(left),
            attempts=int(publishedDict.get("attempts") or 0),
        ).model_dump(mode="json")

    except Exception as exc:
        ctx.step(
            destroySandbox(sandbox=sandboxActive),
            name="kill-sandbox-failed",
            config=RETRY_1,
        )
        return RepairFailed(
            delivery=input.delivery,
            execution_name=input.executionName,
            review_id=str(unpublished.reviewId),
            pr_number=prNumber,
            commit_id=headSha,
            error_name=type(exc).__name__,
            error_message=str(exc) or type(exc).__name__,
        ).model_dump(mode="json")


__all__ = ["RepairPhaseInput", "runRepairPhase"]
