"""Review agent: the production agent phase as plain functions.

``runReviewAgent`` mirrors ``_runAgentPhaseInner``
(``app.workflows.durable.pipeline``) stage for stage — clone,
codegraph index, diff, split, chunks, planner, file batch, extract,
summary, combine — calling the same review workers directly instead of
through durable ``step()`` calls. No DB rows, no GitHub post: the
merged review plus the usage envelope is the return value.
"""

from __future__ import annotations

import logging

from langchain_core.messages import UsageMetadata

from app.services.llm.types import LLMCtx
from app.services.sandbox.types import SandboxCtx
from app.utils.branded import RepoId, UserId
from app.utils.schema import ReviewComments
from app.workflows.review_v2.errors import (
    ReviewStepFailure,
    TransientReviewStepFailure,
)
from app.workflows.review_v2.steps.clone_repo_v2 import cloneRepoV2Step
from app.workflows.review_v2.steps.codegraph_index import (
    installCodeGraphAndIndexRepoStep,
)
from app.workflows.review_v2.steps.combine import (
    buildFileReviewJobs,
    chunkedJobs,
    combineV2Reports,
    concatFileReports,
)
from app.workflows.review_v2.steps.create_sandbox import createSandboxStep
from app.workflows.review_v2.steps.extract_result import (
    buildExtractorLlmCtx,
    extractCommentsStep,
)
from app.workflows.review_v2.steps.fetch_diff import fetchDiffStep
from app.workflows.review_v2.steps.invoke_file import invokeFileReviewStep
from app.workflows.review_v2.steps.invoke_planner import (
    getPlanStep,
    invokePlannerStep,
)
from app.workflows.review_v2.steps.kill_sandbox import killSandboxStep
from app.workflows.review_v2.steps.list_chunks import listChunkFilesStep
from app.workflows.review_v2.steps.split_diff import splitDiffStep
from app.workflows.review_v2.steps.synthesize_summary import synthesizeSummaryStep
from app.workflows.review_v2.types import (
    RepoSnapshot,
    ReviewLimits,
    ReviewWorkflowInput,
)
from app.services.agent_v2.types import PlannerContext

from agents.base import AgentRunError, ReviewOutput

log = logging.getLogger(__name__)


def getStepMessage(stepFailure: ReviewStepFailure) -> str:
    return stepFailure.error.message


def createStepError(agentName: str, stepFailure: ReviewStepFailure) -> AgentRunError:
    return AgentRunError(
        message=getStepMessage(stepFailure),
        agent=agentName,
        retryable=isinstance(stepFailure, TransientReviewStepFailure),
    )


async def runReviewAgent(
    *,
    sandboxCtx: SandboxCtx,
    llm: LLMCtx,
    repo: RepoSnapshot,
    input: ReviewWorkflowInput,
    limits: ReviewLimits,
) -> ReviewOutput | AgentRunError:
    """Review one PR through the production agent stages.

    The clone runs without auth when ``input.githubInstallationId`` is
    absent (the repo is assumed public); otherwise the installation
    token is minted as in production. Failures come back as
    :class:`AgentRunError` values; the sandbox is always destroyed.
    """
    ctx = sandboxCtx
    try:
        ctx = await createSandboxStep(sandboxCtx=sandboxCtx)

        userId = UserId(input.userId)
        repoId: RepoId = repo.id

        await cloneRepoV2Step(
            sandboxCtx=ctx,
            userId=userId,
            repoId=repoId,
            repoOwner=repo.repoOwner,
            repoName=repo.repoName,
            prNumber=input.prNumber,
            headSha=input.headSha,
            githubInstallationId=input.githubInstallationId,
        )
        await installCodeGraphAndIndexRepoStep(
            sandboxCtx=ctx,
            userId=userId,
            repoId=repoId,
            repoName=repo.repoName,
            prNumber=input.prNumber,
            headSha=input.headSha,
        )
        await fetchDiffStep(
            sandboxCtx=ctx,
            repoId=repoId,
            repoName=str(repo.repoName),
            prNumber=input.prNumber,
            headSha=input.headSha,
            baseSha=input.baseSha,
            diffBaseSha=input.diffBaseSha,
        )
        await splitDiffStep(
            sandboxCtx=ctx,
            repoId=repoId,
            prNumber=input.prNumber,
            headSha=input.headSha,
        )
        inventory = await listChunkFilesStep(
            sandboxCtx=ctx,
            repoId=repoId,
            prNumber=input.prNumber,
            headSha=input.headSha,
        )

        try:
            plannerUsage: dict[str, UsageMetadata] = await invokePlannerStep(
                sandboxCtx=ctx,
                llmCtx=llm,
                repo=repo,
                input=input,
                actualFiles=list(inventory.actualFiles),
                limits=limits,
            )
        except ReviewStepFailure as exc:
            log.warning("runReviewAgent: planner degraded: %s", exc)
            plannerUsage = {}
        try:
            plannerContext = await getPlanStep(
                sandboxCtx=ctx,
                repoId=repoId,
                input=input,
            )
        except ReviewStepFailure as exc:
            log.warning("runReviewAgent: no usable plan: %s", exc)
            plannerContext = PlannerContext()

        built = buildFileReviewJobs(
            inventory=inventory,
            plannerContext=plannerContext,
        )
        reports: dict[str, str] = {}
        failed: list[str] = []
        fileUsages: dict[str, dict[str, UsageMetadata]] = {}
        for batch in chunkedJobs(built.jobs):
            for job in batch:
                text: str | None = None
                usage: dict[str, UsageMetadata] = {}
                attempts = 0
                while attempts < 2 and text is None:
                    attempts += 1
                    try:
                        text, usage = await invokeFileReviewStep(
                            filePath=job.filePath,
                            job=job,
                            sharedConcerns=plannerContext.sharedConcerns,
                            sandboxCtx=ctx,
                            llmCtx=llm,
                            repo=repo,
                            input=input,
                            limits=limits,
                            rateLimiterKey=None,
                        )
                    except TransientReviewStepFailure as exc:
                        log.warning(
                            "runReviewAgent: transient file=%s attempt=%d: %s",
                            job.filePath,
                            attempts,
                            exc,
                        )
                        if attempts >= 2:
                            failed.append(job.filePath)
                    except (ReviewStepFailure, Exception) as exc:
                        log.warning(
                            "runReviewAgent: failed file=%s: %s: %s",
                            job.filePath,
                            type(exc).__name__,
                            exc,
                        )
                        failed.append(job.filePath)
                        break
                if text is not None:
                    reports[job.filePath] = text
                    fileUsages[job.filePath] = usage
        if built.jobs and len(failed) == len(built.jobs):
            return AgentRunError(
                message=f"all {len(failed)} file lanes failed",
                agent="review",
            )

        rawText = concatFileReports(reports)
        comments = ReviewComments(List=[])
        if rawText.strip():
            comments, _ = await extractCommentsStep(
                extractorLlmCtx=buildExtractorLlmCtx(),
                rawText=rawText,
            )
        try:
            summary, summaryUsage = await synthesizeSummaryStep(
                input=input,
                repo=repo,
                inventory=inventory,
                plannerContext=plannerContext,
                comments=comments,
            )
            summaryText = summary.summary
        except ReviewStepFailure as exc:
            log.warning("runReviewAgent: summary degraded: %s", exc)
            summaryText = ""
            summaryUsage = {}

        combined = combineV2Reports(
            comments=comments,
            summaryMarkdown=summaryText,
            researchUsages=fileUsages,
            plannerUsage=plannerUsage or None,
            summaryUsage=summaryUsage or None,
            prNumber=input.prNumber,
            headSha=input.headSha,
            repoId=repoId,
            userId=userId,
        )
        return ReviewOutput(
            verdict=combined.review.verdict,
            summary=combined.review.summary,
            comments=list(combined.review.comments),
            model=llm.model,
            usages=combined.usages,
        )
    except TransientReviewStepFailure as stepFailure:
        return createStepError("review", stepFailure)
    except ReviewStepFailure as stepFailure:
        return createStepError("review", stepFailure)
    except Exception as caughtError:  # noqa: BLE001 -- boundary converts to a value
        return AgentRunError(
            message=f"unexpected: {type(caughtError).__name__}: {caughtError}",
            agent="review",
        )
    finally:
        try:
            await killSandboxStep(sandboxCtx=ctx)
        except Exception:  # noqa: BLE001 -- kill never masks the outcome
            pass


__all__ = ["runReviewAgent"]
