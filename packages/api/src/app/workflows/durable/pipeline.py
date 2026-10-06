"""Shared agent phase: sandbox -> clone -> agents -> persist -> post.

Called by both durable handlers after they resolve their inputs. Linear
``ctx.step`` calls only — no closures, no _kill/_fail wrappers. When the
inline post returns ``posted=False`` with comments to show, the pipeline
dispatches the repair durable best-effort before marking SUCCESS. On
exception the except block issues two plain steps (mark failed + destroy)
and returns ``ReviewFailed``. Imports on top.
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

from app.services.agent_v2.types import ChunkInventory, PlannerContext
from app.utils.branded import CommitId, PRNumber, RepoId, UserId
from app.utils.schema import ReviewComments
from app.workflows.durable.steps import (
    clonePrHead,
    createEphemeralSandbox,
    destroySandbox,
    dispatchRepairFollowUp,
    extractReviewComments,
    fetchPrDiff,
    indexCodegraph,
    listDiffChunks,
    markReviewFailed,
    markReviewRunning,
    markReviewSucceeded,
    persistComments,
    persistSummary,
    persistUsage,
    postGithubReview,
    readPlannerOutput,
    runFileBatch,
    runPlanner,
    splitPrDiff,
    synthesizeWalkthrough,
    updateGithubBacklinks,
    upsertPrRow,
)
from app.workflows.durable.types import ReviewCompleted, ReviewFailed
from app.workflows.review_v2.steps.combine import (
    buildFileReviewJobs,
    chunkedJobs,
    combineV2Reports,
    concatFileReports,
)
from app.workflows.review_v2.steps.persist import sumTotalUsages
from app.workflows.review_v2.types import ReviewLimits

log = logging.getLogger(__name__)

RETRY_3 = StepConfig(
    retry_strategy=create_retry_strategy(RetryStrategyConfig(max_attempts=3))
)
RETRY_1 = StepConfig(
    retry_strategy=create_retry_strategy(RetryStrategyConfig(max_attempts=1))
)


class AgentPhaseInput(BaseModel):
    """Everything the agent phase needs (already resolved + validated)."""

    model_config = ConfigDict(frozen=True)

    delivery: str
    executionName: str
    userId: str
    repoId: str
    repo: dict
    workflowInput: dict
    llm: dict
    sandbox: dict
    installationId: int
    prNumber: int
    headSha: str
    baseSha: str
    diffBaseSha: str | None


def runAgentPhase(ctx: DurableContext, *, input: AgentPhaseInput) -> dict:
    repo = input.repo
    workflowInput = input.workflowInput
    llm = input.llm
    userId = input.userId
    repoId = input.repoId
    prNumber = input.prNumber
    headSha = input.headSha
    baseSha = input.baseSha

    modelStr = str(llm.get("model") or "")
    llmProvider = str(llm.get("origin") or "system")
    llmClient = modelStr.split(":")[0] if ":" in modelStr else None
    llmBaseUrl = str(llm.get("baseUrl") or "") or None
    repoName = str(repo.get("repoName") or repo.get("repo_name") or "")
    repoOwner = str(repo.get("repoOwner") or repo.get("repo_owner") or "")
    limits = {"modelCallRunLimit": 120, "toolCallRunLimit": 120}

    reviewRowId: str | None = None
    sandboxActive: dict = dict(input.sandbox)

    try:
        sandboxActive = ctx.step(
            createEphemeralSandbox(sandbox=input.sandbox),
            name="create-sandbox",
            config=RETRY_3,
        )
        prRowId = ctx.step(
            upsertPrRow(input={"repoId": repoId, "workflowInput": workflowInput}),
            name="upsert-pr",
            config=RETRY_3,
        )
        reviewRowId = ctx.step(
            markReviewRunning(
                input={
                    "userId": userId,
                    "repo": repo,
                    "workflowInput": workflowInput,
                    "prRowId": prRowId,
                    "sandboxId": str(sandboxActive.get("sandboxId") or ""),
                    "workflowId": input.executionName,
                    "llmProvider": llmProvider,
                    "llmClient": llmClient,
                    "llmModel": modelStr,
                    "llmBaseUrl": llmBaseUrl,
                }
            ),
            name="mark-running",
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
                    "installationId": input.installationId,
                }
            ),
            name="clone",
            config=RETRY_3,
        )
        ctx.step(
            indexCodegraph(
                input={
                    "sandbox": sandboxActive,
                    "workflowInput": workflowInput,
                    "repoId": repoId,
                    "repoName": repoName,
                }
            ),
            name="codegraph-index",
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
        inventory = ctx.step(
            listDiffChunks(
                input={
                    "sandbox": sandboxActive,
                    "workflowInput": workflowInput,
                    "repoId": repoId,
                }
            ),
            name="list-chunks",
            config=RETRY_3,
        )
        plannerOut = ctx.step(
            runPlanner(
                input={
                    "sandbox": sandboxActive,
                    "llm": llm,
                    "repo": repo,
                    "workflowInput": workflowInput,
                    "actualFiles": list(inventory.get("actualFiles") or []),
                    "limits": limits,
                }
            ),
            name="invoke-planner",
            config=RETRY_3,
        )
        planOut = ctx.step(
            readPlannerOutput(
                input={
                    "sandbox": sandboxActive,
                    "repoId": repoId,
                    "workflowInput": workflowInput,
                }
            ),
            name="get-plan",
            config=RETRY_3,
        )

        plannerContext = planOut.get("planner_context") or PlannerContext().model_dump(
            mode="json"
        )
        plannerModel = PlannerContext.model_validate(plannerContext)
        built = buildFileReviewJobs(
            inventory=ChunkInventory.model_validate(inventory),
            plannerContext=plannerModel,
        )
        reports: dict[str, str] = {}
        failedFiles: list[str] = []
        researchUsages: dict[str, dict] = {}
        for i, batch in enumerate(chunkedJobs(built.jobs)):
            batchOut = ctx.step(
                runFileBatch(
                    input={
                        "sandbox": sandboxActive,
                        "llm": llm,
                        "repo": repo,
                        "workflowInput": workflowInput,
                        "limits": limits,
                        "jobs": [job.model_dump(mode="json") for job in batch],
                        "sharedConcerns": plannerModel.sharedConcerns,
                    }
                ),
                name=f"file-batch-{i}",
                config=RETRY_1,
            )
            reports.update(dict(batchOut.get("reports") or {}))
            failedFiles.extend(list(batchOut.get("failed") or []))
            researchUsages.update(dict(batchOut.get("usages") or {}))
        if built.jobs and len(failedFiles) == len(built.jobs):
            raise RuntimeError(f"all {len(failedFiles)} file lanes failed")

        rawText = concatFileReports(reports)
        commentsList: list[dict] = []
        if rawText.strip():
            extOut = ctx.step(
                extractReviewComments(rawText=rawText),
                name="extract-comments",
                config=RETRY_3,
            )
            commentsList = list(extOut.get("comments") or [])
        summOut = ctx.step(
            synthesizeWalkthrough(
                input={
                    "workflowInput": workflowInput,
                    "repo": repo,
                    "inventory": inventory,
                    "plannerContext": plannerContext,
                    "comments": {"List": commentsList},
                }
            ),
            name="synthesize-summary",
            config=RETRY_1,
        )
        combined = combineV2Reports(
            comments=ReviewComments.model_validate({"List": commentsList}),
            summaryMarkdown=str(summOut.get("summary") or ""),
            researchUsages=researchUsages,
            plannerUsage=dict(plannerOut.get("usage") or {}) or None,
            summaryUsage=dict(summOut.get("usage") or {}) or None,
            prNumber=PRNumber(prNumber),
            headSha=CommitId(headSha),
            repoId=RepoId(repoId),
            userId=UserId(userId),
        )
        reviewDump: dict = combined.review.model_dump(mode="json")
        summaryId = ctx.step(
            persistSummary(
                input={
                    "prRowId": prRowId,
                    "reviewRowId": reviewRowId,
                    "commitId": headSha,
                    "review": reviewDump,
                }
            ),
            name="persist-summary",
            config=RETRY_3,
        )
        commentIds = ctx.step(
            persistComments(
                input={
                    "prRowId": prRowId,
                    "reviewRowId": reviewRowId,
                    "commitId": headSha,
                    "comments": commentsList,
                }
            ),
            name="persist-comments",
            config=RETRY_3,
        )
        inTokens, outTokens, totalTokens, tokenDetails = sumTotalUsages(combined.usages)
        ctx.step(
            persistUsage(
                input={
                    "userId": userId,
                    "prRowId": prRowId,
                    "prNumber": prNumber,
                    "repoId": repoId,
                    "reviewRowId": reviewRowId,
                    "reviewSummaryId": summaryId,
                    "inputTokens": inTokens,
                    "outputTokens": outTokens,
                    "totalTokens": totalTokens,
                    "inputTokenDetails": dict(tokenDetails),
                    "llmModelId": modelStr or None,
                    "llmProvider": llmProvider,
                    "llmBaseUrl": llmBaseUrl,
                }
            ),
            name="persist-usage",
            config=RETRY_3,
        )
        posted = False
        githubReviewId: int | None = None
        postOut = ctx.step(
            postGithubReview(
                input={
                    "repo": repo,
                    "workflowInput": workflowInput,
                    "review": reviewDump,
                }
            ),
            name="post-review",
            config=RETRY_3,
        )
        posted = bool(postOut.get("posted"))
        if not posted and commentsList:
            ctx.step(
                dispatchRepairFollowUp(
                    input={
                        "prNumber": prNumber,
                        "commitId": headSha,
                        "delivery": input.delivery,
                    }
                ),
                name="dispatch-repair",
                config=RETRY_1,
            )
        if posted and postOut.get("githubReviewId") is not None:
            githubReviewId = int(postOut["githubReviewId"])
            ctx.step(
                updateGithubBacklinks(
                    input={
                        "reviewRowId": str(reviewRowId),
                        "reviewSummaryId": summaryId,
                        "commentRowIds": list(commentIds),
                        "githubReviewId": githubReviewId,
                        "repoId": repoId,
                        "prNumber": prNumber,
                    }
                ),
                name="update-backlinks",
                config=RETRY_3,
            )
        ctx.step(
            markReviewSucceeded(
                input={
                    "reviewRowId": str(reviewRowId),
                    "commentCount": len(commentsList),
                    "githubReviewId": str(githubReviewId)
                    if githubReviewId is not None
                    else None,
                    "userId": userId,
                    "repoId": repoId,
                }
            ),
            name="mark-succeeded",
            config=RETRY_3,
        )
        ctx.step(
            destroySandbox(sandbox=sandboxActive),
            name="kill-sandbox-done",
            config=RETRY_1,
        )
        log.info(
            "pipeline: complete delivery=%s pr=%s verdict=%s comments=%d posted=%s",
            input.delivery,
            prNumber,
            combined.review.verdict,
            len(commentsList),
            posted,
        )
        return ReviewCompleted(
            delivery=input.delivery,
            execution_name=input.executionName,
            workflow_id=input.executionName,
            review_id=str(reviewRowId),
            repo_id=repoId,
            pr_number=prNumber,
            head_sha=headSha,
            base_sha=baseSha,
            diff_base_sha=input.diffBaseSha,
            user_id=userId,
            verdict=str(combined.review.verdict),
            comment_count=len(commentsList),
            posted=posted,
            github_review_id=githubReviewId,
        ).model_dump(mode="json")

    except Exception as exc:
        ctx.step(
            markReviewFailed(
                input={
                    "reviewRowId": reviewRowId,
                    "errorName": type(exc).__name__,
                    "errorMessage": str(exc) or type(exc).__name__,
                    "errorContext": None,
                    "userId": userId,
                    "repoId": repoId,
                }
            ),
            name="mark-failed",
            config=RETRY_1,
        )
        ctx.step(
            destroySandbox(sandbox=sandboxActive),
            name="kill-sandbox-failed",
            config=RETRY_1,
        )
        return ReviewFailed(
            delivery=input.delivery,
            execution_name=input.executionName,
            repo_id=repoId,
            pr_number=prNumber,
            head_sha=headSha,
            user_id=userId,
            error_name=type(exc).__name__,
            error_message=str(exc) or type(exc).__name__,
        ).model_dump(mode="json")


__all__ = ["AgentPhaseInput", "runAgentPhase"]
