"""Shared agent phase: sandbox -> clone -> agents -> persist -> post.

Called by both durable handlers after they resolve their inputs. Linear
``await step(...)`` calls only — no closures, no _kill/_fail wrappers.
When the inline post returns ``posted=False`` with comments to show, the
pipeline dispatches the repair durable best-effort before marking
SUCCESS. On exception the except block issues two plain steps (mark
failed + destroy) and returns ``ReviewFailed``. Imports on top.
"""

from __future__ import annotations

import logging

from async_durable_execution import step
from langfuse import observe, propagate_attributes
from pydantic import BaseModel, ConfigDict

from app.core.config import settings
from app.services.agent_v2.types import ChunkInventory, PlannerContext
from app.utils.branded import CommitId, PRNumber, RepoId, UserId
from app.utils.schema import ReviewComments
from app.workflows.durable.retry import RETRY_1, RETRY_3
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

log = logging.getLogger(__name__)


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


@observe(name="run-agent-phase", capture_input=False, capture_output=False)
async def runAgentPhase(*, input: AgentPhaseInput) -> dict:
    """Parent review trace: sets user/session attrs, runs the agent phase."""
    llmDict: dict[str, object] = dict(input.llm)
    repoDict: dict[str, object] = dict(input.repo)
    workflowDict: dict[str, object] = dict(input.workflowInput)
    modelStr: str = str(llmDict.get("model") or "")
    llmOrigin: str = str(llmDict.get("origin") or "system")
    repoName: str = str(repoDict.get("repoName") or repoDict.get("repo_name") or "")
    trigger: str = str(workflowDict.get("trigger") or "opened")
    shortSha: str = input.headSha[:7] if len(input.headSha) >= 7 else input.headSha
    sessionId: str = f"review:{input.userId}:{input.repoId}:{input.prNumber}:{shortSha}"
    tags: list[str] = [f"trigger:{trigger}", f"pr:{input.prNumber}"]
    if repoName:
        tags.append(f"repo:{repoName}")
    metadata: dict[str, str | int] = {
        "delivery": input.delivery,
        "trigger": trigger,
        "repo_id": input.repoId,
        "pr_number": input.prNumber,
        "head_sha": input.headSha,
        "base_sha": input.baseSha,
        "llm_model": modelStr,
        "llm_origin": llmOrigin,
    }
    if repoName:
        metadata["repo_name"] = repoName
    with propagate_attributes(
        user_id=input.userId,
        session_id=sessionId,
        tags=tags,
        metadata=metadata,
        version=settings.app_version,
        environment=settings.app_env,
        trace_name="review-run",
    ):
        return await _runAgentPhaseInner(input=input)


async def _runAgentPhaseInner(*, input: AgentPhaseInput) -> dict:
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
        sandboxActive = await step(
            createEphemeralSandbox(sandbox=input.sandbox),
            name="create-sandbox",
            retry_strategy=RETRY_3,
        )
        prRowId = await step(
            upsertPrRow(input={"repoId": repoId, "workflowInput": workflowInput}),
            name="upsert-pr",
            retry_strategy=RETRY_3,
        )
        reviewRowId = await step(
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
                    "installationId": input.installationId,
                }
            ),
            name="clone",
            retry_strategy=RETRY_3,
        )
        await step(
            indexCodegraph(
                input={
                    "sandbox": sandboxActive,
                    "workflowInput": workflowInput,
                    "repoId": repoId,
                    "repoName": repoName,
                }
            ),
            name="codegraph-index",
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
        inventory = await step(
            listDiffChunks(
                input={
                    "sandbox": sandboxActive,
                    "workflowInput": workflowInput,
                    "repoId": repoId,
                }
            ),
            name="list-chunks",
            retry_strategy=RETRY_3,
        )
        plannerOut = await step(
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
            retry_strategy=RETRY_3,
        )
        planOut = await step(
            readPlannerOutput(
                input={
                    "sandbox": sandboxActive,
                    "repoId": repoId,
                    "workflowInput": workflowInput,
                }
            ),
            name="get-plan",
            retry_strategy=RETRY_3,
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
            batchOut = await step(
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
                retry_strategy=RETRY_1,
            )
            reports.update(dict(batchOut.get("reports") or {}))
            failedFiles.extend(list(batchOut.get("failed") or []))
            researchUsages.update(dict(batchOut.get("usages") or {}))
        if built.jobs and len(failedFiles) == len(built.jobs):
            raise RuntimeError(f"all {len(failedFiles)} file lanes failed")

        rawText = concatFileReports(reports)
        commentsList: list[dict] = []
        if rawText.strip():
            extOut = await step(
                extractReviewComments(rawText=rawText),
                name="extract-comments",
                retry_strategy=RETRY_3,
            )
            commentsList = list(extOut.get("comments") or [])
        summOut = await step(
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
            retry_strategy=RETRY_1,
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
        summaryId = await step(
            persistSummary(
                input={
                    "prRowId": prRowId,
                    "reviewRowId": reviewRowId,
                    "commitId": headSha,
                    "review": reviewDump,
                }
            ),
            name="persist-summary",
            retry_strategy=RETRY_3,
        )
        commentIds = await step(
            persistComments(
                input={
                    "prRowId": prRowId,
                    "reviewRowId": reviewRowId,
                    "commitId": headSha,
                    "comments": commentsList,
                }
            ),
            name="persist-comments",
            retry_strategy=RETRY_3,
        )
        inTokens, outTokens, totalTokens, tokenDetails = sumTotalUsages(combined.usages)
        await step(
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
            retry_strategy=RETRY_3,
        )
        posted = False
        githubReviewId: int | None = None
        postOut = await step(
            postGithubReview(
                input={
                    "repo": repo,
                    "workflowInput": workflowInput,
                    "review": reviewDump,
                }
            ),
            name="post-review",
            retry_strategy=RETRY_3,
        )
        posted = bool(postOut.get("posted"))
        if not posted and commentsList:
            await step(
                dispatchRepairFollowUp(
                    input={
                        "prNumber": prNumber,
                        "commitId": headSha,
                        "delivery": input.delivery,
                    }
                ),
                name="dispatch-repair",
                retry_strategy=RETRY_1,
            )
        if posted and postOut.get("githubReviewId") is not None:
            githubReviewId = int(postOut["githubReviewId"])
            await step(
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
                retry_strategy=RETRY_3,
            )
        await step(
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
            retry_strategy=RETRY_3,
        )
        await step(
            destroySandbox(sandbox=sandboxActive),
            name="kill-sandbox-done",
            retry_strategy=RETRY_1,
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
        await step(
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
            retry_strategy=RETRY_1,
        )
        await step(
            destroySandbox(sandbox=sandboxActive),
            name="kill-sandbox-failed",
            retry_strategy=RETRY_1,
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
