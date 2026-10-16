"""Shared repair phase: load unpublished review -> sandbox -> repair -> save.

Called by the repair durable handler. Linear ``await step(...)`` calls
only — no closures, no wrappers. Ctx resolution (load + LLM + sandbox)
returns early with ``RepairSkipped``; the agent phase is wrapped in
try/except that issues one plain destroy step and returns
``RepairFailed``. Imports on top.
"""

from __future__ import annotations

import logging

from async_durable_execution import step
from langfuse import observe, propagate_attributes
from pydantic import BaseModel, ConfigDict

from app.core.config import settings
from app.workflows.durable.retry import RETRY_1, RETRY_3
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


class RepairPhaseInput(BaseModel):
    """Everything the repair phase needs (already validated)."""

    model_config = ConfigDict(frozen=True)

    delivery: str
    executionName: str
    commitId: str


@observe(name="run-repair-phase", capture_input=False, capture_output=False)
async def runRepairPhase(*, input: RepairPhaseInput) -> dict:
    unpublishedDict = await step(
        loadUnpublishedReview(commitId=input.commitId),
        name="load-unpublished",
        retry_strategy=RETRY_3,
    )
    if unpublishedDict is None:
        return RepairSkipped(
            delivery=input.delivery, skip_reason="nothing_to_publish"
        ).model_dump(mode="json")

    unpublished = UnpublishedReview.model_validate(unpublishedDict)
    userId = str(unpublished.userId)
    repoId = str(unpublished.repoId)
    repoName = str(unpublished.repoName)
    prNumber = int(unpublished.prNumber)
    headSha = str(unpublished.commitId)

    llm = await step(
        resolveActiveLlmCtx(userId=userId),
        name="resolve-llm",
        retry_strategy=RETRY_3,
    )
    sandbox = await step(
        buildSandboxCtxForRun(
            input={"userId": userId, "repoId": repoId, "repoName": repoName}
        ),
        name="build-sandbox",
        retry_strategy=RETRY_1,
    )

    log.info(
        "repair: ctx resolved delivery=%s pr=%s commit=%s comments=%d",
        input.delivery,
        prNumber,
        headSha[:7],
        len(unpublished.comments),
    )

    llmDict: dict[str, object] = dict(llm)
    modelStr: str = str(llmDict.get("model") or "")
    llmOrigin: str = str(llmDict.get("origin") or "system")
    shortSha: str = headSha[:7] if len(headSha) >= 7 else headSha
    sessionId: str = f"review:{userId}:{repoId}:{prNumber}:{shortSha}"
    tags: list[str] = ["trigger:repair", f"pr:{prNumber}"]
    if repoName:
        tags.append(f"repo:{repoName}")
    metadata: dict[str, str | int] = {
        "delivery": input.delivery,
        "trigger": "repair",
        "repo_id": repoId,
        "pr_number": prNumber,
        "head_sha": headSha,
        "llm_model": modelStr,
        "llm_origin": llmOrigin,
    }
    if repoName:
        metadata["repo_name"] = repoName
    with propagate_attributes(
        user_id=userId,
        session_id=sessionId,
        tags=tags,
        metadata=metadata,
        version=settings.app_version,
        environment=settings.app_env,
        trace_name="repair-run",
    ):
        return await _runRepairAgentPhaseInner(
            input=input,
            unpublished=unpublished,
            unpublishedDict=dict(unpublishedDict),
            llm=dict(llm),
            sandbox=dict(sandbox),
        )


async def _runRepairAgentPhaseInner(
    *,
    input: RepairPhaseInput,
    unpublished: UnpublishedReview,
    unpublishedDict: dict[str, object],
    llm: dict[str, object],
    sandbox: dict[str, object],
) -> dict:
    userId = str(unpublished.userId)
    repoId = str(unpublished.repoId)
    repoName = str(unpublished.repoName)
    repoOwner = str(unpublished.repoOwner)
    prNumber = int(unpublished.prNumber)
    headSha = str(unpublished.commitId)
    baseSha = str(unpublished.baseSha or unpublished.commitId)
    installationId = int(unpublished.installationId)

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
        sandboxActive = await step(
            createEphemeralSandbox(sandbox=sandbox),
            name="create-sandbox",
            retry_strategy=RETRY_3,
        )
        await step(
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
            retry_strategy=RETRY_3,
        )
        await step(
            fetchPrDiff(
                input={
                    "sandbox": sandboxActive,
                    "workflowInput": workflowInput,
                    "repoId": repoId,
                    "repoName": repoName,
                }
            ),
            name="fetch-diff",
            retry_strategy=RETRY_3,
        )
        await step(
            splitPrDiff(
                input={
                    "sandbox": sandboxActive,
                    "workflowInput": workflowInput,
                    "repoId": repoId,
                }
            ),
            name="split-diff",
            retry_strategy=RETRY_3,
        )
        diffDir = getReviewDiffDirPath(prNumber, headSha)
        await step(
            deleteClonedRepo(input={"sandbox": sandboxActive, "repoName": repoName}),
            name="delete-repo",
            retry_strategy=RETRY_1,
        )
        publishedDict = await step(
            runRepairAgent(
                input={
                    "llm": llm,
                    "unpublished": unpublishedDict,
                    "sandbox": sandboxActive,
                    "diffDir": diffDir,
                }
            ),
            name="run-repair-agent",
            retry_strategy=RETRY_3,
        )
        if publishedDict is None:
            await step(
                destroySandbox(sandbox=sandboxActive),
                name="kill-sandbox-done",
                retry_strategy=RETRY_1,
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

        await step(
            savePublishOutcome(
                input={"unpublished": unpublishedDict, "published": publishedDict}
            ),
            name="save-published",
            retry_strategy=RETRY_3,
        )
        await step(
            destroySandbox(sandbox=sandboxActive),
            name="kill-sandbox-done",
            retry_strategy=RETRY_1,
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
        await step(
            destroySandbox(sandbox=sandboxActive),
            name="kill-sandbox-failed",
            retry_strategy=RETRY_1,
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
