"""Eval runner: dataset list in, review plus judge, stored evaluations out.

``runEval`` loads dataset entries (title, PR URL, description, golden
comments), resolves each PR URL to live GitHub facts (SHAs, branches),
runs ``runReviewAgent`` (production stages, called directly), judges
generated comments against golden comments, prints per-PR plus dataset
metrics, and stores ``results/{modelId}/evaluations.json``.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import cast

from app.core.config import settings
from app.models.enums import PRStatus
from app.services.llm.types import LLMCtx
from app.services.sandbox.service import createSandboxCtx
from app.services.sandbox.types import ProviderId, SanboxProviderApiKey
from app.utils.branded import (
    ApiKey,
    BaseUrl,
    CommitId,
    PRNumber,
    RepoId,
    RepoName,
    RepoOwner,
    UserId,
)
from app.utils.schema import CodeCommentDraft
from app.workflows.review_v2.types import (
    RepoSnapshot,
    ReviewLimits,
    ReviewWorkflowInput,
)
from pydantic import BaseModel, ConfigDict, Field

from agents.base import AgentRunError, ReviewOutput
from agents.judge import JUDGE_SYSTEM_PROMPT, JudgeResult, runJudgeAgent
from agents.review import runReviewAgent
from datasetLoader.loader import loadDatasetEntries
from datasetLoader.prResolver import parsePrUrlParts, resolvePrUrl
from datasetLoader.types import (
    DatasetEntry,
    DatasetLoaderError,
    GoldenComment,
    PrContext,
    PrResolverError,
)
from environments.base import EnvKind
from metrics.scoring import (
    DatasetMetrics,
    PrScore,
    createDatasetMetrics,
    failedPrScore,
    scoreSingleResult,
)
from providers import registerEvalProviders
from resultStore.types import PrEvaluation, buildResolvedRef
from resultStore.writer import (
    buildEvaluationsFile,
    buildEvaluationsFilePath,
    saveEvaluationsFile,
)

log = logging.getLogger(__name__)

evalUserId = UserId("eval-user")


class RunConfig(BaseModel):
    """Everything one ``runEval`` needs."""

    model_config = ConfigDict(frozen=True)

    datasetPath: str = Field(min_length=1)
    env: EnvKind = Field(default="local")
    model: str = Field(default="openai:gpt-5-mini", min_length=3)
    baseUrl: str = Field(default="")
    apiKey: str = Field(default="")
    githubToken: str = Field(default="")
    judgePrompt: str = Field(default=JUDGE_SYSTEM_PROMPT, min_length=1)
    resultsDir: str = Field(default="results", min_length=1)


class RunError(BaseModel):
    """Runner-level failure, returned as a value (never raised)."""

    model_config = ConfigDict(frozen=True)

    message: str
    phase: str = Field(default="")

    def __str__(self) -> str:
        return self.message


def buildLlmContext(runConfig: RunConfig) -> LLMCtx | RunError:
    if ":" not in runConfig.model:
        return RunError(
            message=f"model must be 'provider:model', got {runConfig.model!r}",
            phase="config",
        )
    return LLMCtx(
        model=runConfig.model,
        origin="system",
        apiKey=ApiKey(runConfig.apiKey) if runConfig.apiKey else None,
        baseUrl=BaseUrl(runConfig.baseUrl) if runConfig.baseUrl else None,
        defaultHeaders={},
        maxRetries=3,
        rateLimitRps=0.5,
    )


def resolveSandboxApiKey(runConfig: RunConfig) -> str:
    if runConfig.apiKey:
        return runConfig.apiKey
    if runConfig.env == "e2b":
        return settings.e2b_api_key
    return ""


def resolveGithubToken(runConfig: RunConfig) -> str | None:
    cleanedFlagToken = runConfig.githubToken.strip()
    if cleanedFlagToken:
        return cleanedFlagToken
    envToken = os.environ.get("GITHUB_TOKEN", "").strip()
    return envToken or None


def buildCaseId(entryIndex: int, datasetEntry: DatasetEntry) -> str:
    urlParts = parsePrUrlParts(datasetEntry.prUrl)
    if isinstance(urlParts, PrResolverError):
        return f"case-{entryIndex + 1}"
    return f"{urlParts.owner}-{urlParts.repo}-{urlParts.prNumber}"


def buildRepoContext(prContext: PrContext) -> RepoSnapshot:
    return RepoSnapshot(
        id=RepoId(f"eval-{prContext.owner}-{prContext.repoName}-{prContext.prNumber}"),
        repoOwner=RepoOwner(prContext.owner),
        repoName=RepoName(prContext.repoName),
        defaultBranch=prContext.baseBranch,
    )


def selectEntryTitle(datasetEntry: DatasetEntry, resolvedContext: PrContext) -> str:
    cleanedEntryTitle = datasetEntry.title.strip()
    if cleanedEntryTitle:
        return datasetEntry.title
    if resolvedContext.fetchedTitle:
        return resolvedContext.fetchedTitle
    return f"{resolvedContext.repoName} PR {resolvedContext.prNumber}"


def selectEntryBody(datasetEntry: DatasetEntry, resolvedContext: PrContext) -> str:
    cleanedEntryBody = datasetEntry.description.strip()
    if cleanedEntryBody:
        return datasetEntry.description
    return resolvedContext.fetchedBody


def buildWorkflowInput(
    datasetEntry: DatasetEntry, resolvedContext: PrContext
) -> ReviewWorkflowInput:
    return ReviewWorkflowInput(
        userId=evalUserId,
        ghRepoId=0,
        ghPrId=0,
        prNumber=PRNumber(resolvedContext.prNumber),
        baseBranch=resolvedContext.baseBranch,
        defaultBranch=resolvedContext.baseBranch,
        baseSha=resolvedContext.baseSha,
        headSha=CommitId(resolvedContext.headSha),
        headBranch=resolvedContext.headBranch,
        author=resolvedContext.author,
        title=selectEntryTitle(datasetEntry, resolvedContext),
        body=selectEntryBody(datasetEntry, resolvedContext),
        status=PRStatus.OPEN,
        trigger="eval",
        postToGithub=False,
        githubInstallationId=None,
        diffBaseSha=None,
    )


def buildPrEvaluation(
    caseId: str,
    datasetEntry: DatasetEntry,
    prScore: PrScore,
    judgeResult: JudgeResult | None,
    generatedComments: list[CodeCommentDraft],
    goldenComments: list[GoldenComment],
    prContext: PrContext | None,
    error: str | None,
) -> PrEvaluation:
    return PrEvaluation(
        caseId=caseId,
        prUrl=datasetEntry.prUrl,
        title=datasetEntry.title,
        prScore=prScore,
        judgeResult=judgeResult,
        generatedComments=list(generatedComments),
        goldenComments=list(goldenComments),
        resolved=buildResolvedRef(prContext),
        error=error,
    )


def recordFailedEvaluation(
    caseId: str,
    datasetEntry: DatasetEntry,
    prContext: PrContext | None,
    reason: str,
    itemScores: list[PrScore],
    evaluations: list[PrEvaluation],
) -> None:
    failedScore = failedPrScore(caseId, datasetEntry.prUrl, datasetEntry.title, reason)
    itemScores.append(failedScore)
    evaluations.append(
        buildPrEvaluation(
            caseId,
            datasetEntry,
            failedScore,
            None,
            [],
            list(datasetEntry.comments),
            prContext,
            reason,
        )
    )
    printSinglePrResult(failedScore)


def recordReviewEvaluation(
    caseId: str,
    datasetEntry: DatasetEntry,
    prContext: PrContext,
    reviewOutput: ReviewOutput,
    judgeResult: JudgeResult,
    itemScores: list[PrScore],
    evaluations: list[PrEvaluation],
) -> None:
    prScore = scoreSingleResult(
        judgeResult,
        caseId=caseId,
        prUrl=datasetEntry.prUrl,
        title=datasetEntry.title,
    )
    itemScores.append(prScore)
    evaluations.append(
        buildPrEvaluation(
            caseId,
            datasetEntry,
            prScore,
            judgeResult,
            list(reviewOutput.comments),
            list(datasetEntry.comments),
            prContext,
            None,
        )
    )
    printSinglePrResult(prScore)


def printSinglePrResult(prScore: PrScore) -> None:
    print(
        f"[{prScore.caseId}] {prScore.title} | {prScore.prUrl} | "
        f"confidence={prScore.confidence:.3f} "
        f"matched={prScore.matchedCount}/{prScore.totalGoldenCount} "
        f"falsePositives={prScore.falsePositiveCount} "
        f"generated={prScore.generatedCount} "
        f"recall={prScore.recall:.3f}"
        + (f" error={prScore.error}" if prScore.error is not None else "")
    )


def printDatasetMetricsReport(datasetMetrics: DatasetMetrics, evaluationsPath: Path) -> None:
    print(f"dataset: {datasetMetrics.summary()}")
    if datasetMetrics.failedIds:
        print(f"failed: {', '.join(datasetMetrics.failedIds)}")
    print(f"saved: {evaluationsPath}")


async def runEval(runConfig: RunConfig) -> DatasetMetrics | RunError:
    """Run the dataset list, print metrics, and store evaluations.json."""
    loadedDataset = loadDatasetEntries(runConfig.datasetPath)
    if isinstance(loadedDataset, DatasetLoaderError):
        return RunError(message=str(loadedDataset), phase="load")

    llmContext = buildLlmContext(runConfig)
    if isinstance(llmContext, RunError):
        return llmContext

    registerEvalProviders()
    reviewLimits = ReviewLimits(modelCallRunLimit=120, toolCallRunLimit=120)
    githubToken = resolveGithubToken(runConfig)
    sandboxApiKey = resolveSandboxApiKey(runConfig)

    itemScores: list[PrScore] = []
    evaluations: list[PrEvaluation] = []
    for entryIndex, datasetEntry in enumerate(loadedDataset.entries):
        caseId = buildCaseId(entryIndex, datasetEntry)
        prContext = await resolvePrUrl(datasetEntry.prUrl, githubToken)
        if isinstance(prContext, PrResolverError):
            log.warning("eval resolve failed: %s: %s", caseId, prContext.message)
            recordFailedEvaluation(caseId, datasetEntry, None, prContext.message, itemScores, evaluations)
            continue
        repoContext = buildRepoContext(prContext)
        try:
            sandboxContext = createSandboxCtx(
                userId=evalUserId,
                repoId=repoContext.id,
                repoName=prContext.repoName,
                providerId=cast(ProviderId, runConfig.env),
                apiKey=SanboxProviderApiKey(sandboxApiKey),
                sandboxName=f"eval-{prContext.repoName}-{prContext.prNumber}",
                rootPath="/home/user",
            )
        except Exception as caughtError:
            failureMessage = f"sandbox ctx: {type(caughtError).__name__}: {caughtError}"
            log.warning("eval case failed: %s: %s", caseId, failureMessage)
            recordFailedEvaluation(caseId, datasetEntry, prContext, failureMessage, itemScores, evaluations)
            continue
        workflowInput = buildWorkflowInput(datasetEntry, prContext)
        reviewOutput = await runReviewAgent(
            sandboxCtx=sandboxContext,
            llm=llmContext,
            repo=repoContext,
            input=workflowInput,
            limits=reviewLimits,
        )
        if isinstance(reviewOutput, AgentRunError):
            log.warning("eval case failed: %s: %s", caseId, reviewOutput.message)
            recordFailedEvaluation(
                caseId, datasetEntry, prContext, reviewOutput.message, itemScores, evaluations
            )
            continue
        judgeResult = await runJudgeAgent(
            generatedComments=list(reviewOutput.comments),
            goldenComments=list(datasetEntry.comments),
            llm=llmContext,
            systemPrompt=runConfig.judgePrompt,
        )
        if isinstance(judgeResult, AgentRunError):
            log.warning("eval judge failed: %s: %s", caseId, judgeResult.message)
            recordFailedEvaluation(
                caseId, datasetEntry, prContext, judgeResult.message, itemScores, evaluations
            )
            continue
        recordReviewEvaluation(caseId, datasetEntry, prContext, reviewOutput, judgeResult, itemScores, evaluations)
    datasetMetrics = createDatasetMetrics(itemScores)
    evaluationsFile = buildEvaluationsFile(
        runConfig.datasetPath, str(runConfig.env), datasetMetrics, evaluations
    )
    evaluationsPath = buildEvaluationsFilePath(Path(runConfig.resultsDir), runConfig.model)
    saveError = saveEvaluationsFile(evaluationsPath, evaluationsFile)
    if saveError is not None:
        return RunError(message=str(saveError), phase="save")
    printDatasetMetricsReport(datasetMetrics, evaluationsPath)
    log.info("eval complete: %s", datasetMetrics.summary())
    return datasetMetrics


__all__ = ["RunConfig", "RunError", "runEval"]
