"""Persist/post/lifecycle steps: DB rows and GitHub post.

Each step validates its input first, runs one worker via asyncio.run,
returns model_dump. Imports on top. Fail-closed steps propagate for
SDK retry; post returns posted=False on terminal 4xx.
"""

from __future__ import annotations

import asyncio
from uuid import UUID

from aws_durable_execution_sdk_python import durable_step
from aws_durable_execution_sdk_python.types import StepContext
from pydantic import BaseModel, ConfigDict

from app.utils.branded import (
    CommitId,
    PrRowId,
    PRNumber,
    RepoId,
    ReviewRowId,
    UserId,
)
from app.utils.schema import CodeCommentDraft, ReviewResult
from app.workflows.review_v2.steps.persist import (
    persistCodeCommentsTx,
    persistReviewSummaryTx,
    persistReviewUsageTx,
)
from app.workflows.review_v2.steps.post_review import (
    postReviewStep,
    updatePostBacklinksTx,
)
from app.workflows.review_v2.steps.review_lifecycle import (
    markReviewErroredStep,
    markReviewRunningStep,
    markReviewStoppedStep,
)
from app.workflows.review_v2.steps.upsert_pr import upsertPullRequestTx
from app.workflows.review_v2.types import RepoSnapshot, ReviewWorkflowInput


class UpsertPrInput(BaseModel):
    model_config = ConfigDict(frozen=True)

    repoId: RepoId
    workflowInput: ReviewWorkflowInput


@durable_step
def upsertPrRow(_ctx: StepContext, *, input: dict) -> str:
    """Insert/update the pull_requests row; returns the row id."""
    request = UpsertPrInput.model_validate(input)
    return str(
        asyncio.run(
            upsertPullRequestTx(
                repoId=request.repoId,
                input=request.workflowInput,
            )
        )
    )


class MarkRunningInput(BaseModel):
    model_config = ConfigDict(frozen=True)

    userId: UserId
    repo: RepoSnapshot
    workflowInput: ReviewWorkflowInput
    prRowId: PrRowId
    sandboxId: str
    workflowId: str
    llmProvider: str
    llmClient: str | None
    llmModel: str
    llmBaseUrl: str | None


@durable_step
def markReviewRunning(_ctx: StepContext, *, input: dict) -> str:
    """Find-or-create the RUNNING lifecycle row; returns review row id."""
    request = MarkRunningInput.model_validate(input)
    return str(
        asyncio.run(
            markReviewRunningStep(
                userId=request.userId,
                repo=request.repo,
                input=request.workflowInput,
                prRowId=request.prRowId,
                sandboxId=request.sandboxId,
                workflowId=request.workflowId,
                llmProvider=request.llmProvider,
                llmClient=request.llmClient,
                llmModel=request.llmModel,
                llmBaseUrl=request.llmBaseUrl,
            )
        )
    )


class MarkSucceededInput(BaseModel):
    model_config = ConfigDict(frozen=True)

    reviewRowId: ReviewRowId
    commentCount: int
    githubReviewId: str | None
    userId: UserId
    repoId: RepoId


@durable_step
def markReviewSucceeded(_ctx: StepContext, *, input: dict) -> dict:
    """Flip the lifecycle row to SUCCESS."""
    request = MarkSucceededInput.model_validate(input)
    asyncio.run(
        markReviewStoppedStep(
            reviewRowId=request.reviewRowId,
            commentCount=request.commentCount,
            githubReviewId=request.githubReviewId,
            userId=request.userId,
            repoId=request.repoId,
        )
    )
    return {}


class MarkFailedInput(BaseModel):
    model_config = ConfigDict(frozen=True)

    reviewRowId: ReviewRowId | None
    errorName: str
    errorMessage: str
    errorContext: dict | None
    userId: UserId
    repoId: RepoId


@durable_step
def markReviewFailed(_ctx: StepContext, *, input: dict) -> dict:
    """Flip the lifecycle row to FAILED (noops when row was never made)."""
    request = MarkFailedInput.model_validate(input)
    asyncio.run(
        markReviewErroredStep(
            reviewRowId=request.reviewRowId,
            errorName=request.errorName,
            errorMessage=request.errorMessage,
            errorContext=request.errorContext,
            userId=request.userId,
            repoId=request.repoId,
        )
    )
    return {}


class PersistSummaryInput(BaseModel):
    model_config = ConfigDict(frozen=True)

    prRowId: PrRowId
    reviewRowId: ReviewRowId | None
    commitId: CommitId
    review: ReviewResult


@durable_step
def persistSummary(_ctx: StepContext, *, input: dict) -> str:
    """Persist the review_summaries row; returns the summary id."""
    request = PersistSummaryInput.model_validate(input)
    return str(
        asyncio.run(
            persistReviewSummaryTx(
                prRowId=request.prRowId,
                reviewRowId=request.reviewRowId,
                commitId=request.commitId,
                review=request.review,
            )
        )
    )


class PersistCommentsInput(BaseModel):
    model_config = ConfigDict(frozen=True)

    prRowId: PrRowId
    reviewRowId: ReviewRowId | None
    commitId: CommitId
    comments: list[CodeCommentDraft]


@durable_step
def persistComments(_ctx: StepContext, *, input: dict) -> list[str]:
    """Persist the code_comments rows; returns the row ids."""
    request = PersistCommentsInput.model_validate(input)
    return list(
        asyncio.run(
            persistCodeCommentsTx(
                prRowId=request.prRowId,
                reviewRowId=request.reviewRowId,
                commitId=request.commitId,
                comments=list(request.comments),
            )
        )
    )


class PersistUsageInput(BaseModel):
    model_config = ConfigDict(frozen=True)

    userId: UserId
    prRowId: PrRowId
    prNumber: PRNumber
    repoId: RepoId
    reviewRowId: ReviewRowId | None
    reviewSummaryId: str | None
    inputTokens: int
    outputTokens: int
    totalTokens: int
    inputTokenDetails: dict | None
    llmModelId: str | None
    llmProvider: str | None
    llmBaseUrl: str | None


@durable_step
def persistUsage(_ctx: StepContext, *, input: dict) -> str:
    """Persist the review_usages row; returns the row id."""
    request = PersistUsageInput.model_validate(input)
    return str(
        asyncio.run(
            persistReviewUsageTx(
                userId=request.userId,
                prRowId=request.prRowId,
                prNumber=request.prNumber,
                repoId=request.repoId,
                reviewRowId=request.reviewRowId,
                reviewSummaryId=UUID(request.reviewSummaryId)
                if request.reviewSummaryId
                else None,
                inputTokens=request.inputTokens,
                outputTokens=request.outputTokens,
                totalTokens=request.totalTokens,
                inputTokenDetails=request.inputTokenDetails,
                llmModelId=request.llmModelId,
                llmProvider=request.llmProvider,
                llmBaseUrl=request.llmBaseUrl,
            )
        )
    )


class PostReviewInput(BaseModel):
    model_config = ConfigDict(frozen=True)

    repo: RepoSnapshot
    workflowInput: ReviewWorkflowInput
    review: ReviewResult


@durable_step
def postGithubReview(_ctx: StepContext, *, input: dict) -> dict:
    """Post the review inline; 4xx returns posted=False."""
    request = PostReviewInput.model_validate(input)
    return asyncio.run(
        postReviewStep(
            repo=request.repo,
            input=request.workflowInput,
            review=request.review,
        )
    ).model_dump(mode="json")


class BacklinksInput(BaseModel):
    model_config = ConfigDict(frozen=True)

    reviewRowId: ReviewRowId
    reviewSummaryId: str
    commentRowIds: list[str]
    githubReviewId: int
    repoId: RepoId
    prNumber: PRNumber


@durable_step
def updateGithubBacklinks(_ctx: StepContext, *, input: dict) -> dict:
    """Write GitHub review/comment ids back onto local rows."""
    request = BacklinksInput.model_validate(input)
    asyncio.run(
        updatePostBacklinksTx(
            reviewRowId=request.reviewRowId,
            reviewSummaryId=request.reviewSummaryId,
            commentRowIds=list(request.commentRowIds),
            githubReviewId=request.githubReviewId,
            repoId=request.repoId,
            prNumber=request.prNumber,
        )
    )
    return {}


__all__ = [
    "markReviewFailed",
    "markReviewRunning",
    "markReviewSucceeded",
    "persistComments",
    "persistSummary",
    "persistUsage",
    "postGithubReview",
    "updateGithubBacklinks",
    "upsertPrRow",
]
