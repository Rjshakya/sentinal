"""Main review durable workflow.

This module owns the top-level :func:`reviewWorkflow` DBOS workflow
that sequences the review pipeline, plus its pure workflow helpers:

- :func:`reviewWorkflow` — the orchestrator. Every step is implemented
  in :mod:`app.workflows.review.steps`; every shared Pydantic type is
  in :mod:`app.workflows.review.types`. The workflow takes the
  serializable :class:`ReviewWorkflowCtx` (resolved LLM + sandbox
  environment, built at the edge) next to the PR-specific
  :class:`ReviewWorkflowInput`.
- :func:`createReviewWorkflowId` — the deterministic
  ``review:{repo_id}:{pr_number}:{head_sha[:7]}`` id.
- :func:`computeReviewLimits` — sizes the per-run agent call limits
  from the PR's size stats.
- :func:`buildReviewWorkflowInput` — pure input builder for the
  trigger adapters.

Design notes:

- All workflow inputs and outputs are Pydantic models so DBOS can
  serialise them into its system database.
- Steps raise on failure; transient failures are retried by DBOS via
  the shared :func:`app.workflows.review.errors.shouldRetry`
  predicate, business outcomes propagate and mark the workflow ERROR.
- The sandbox object is never passed between steps — only the
  :class:`SandboxCtx` (its serializable handle, carrying ``sandboxId``)
  travels; each step reconnects by id.
- The pipeline is **stateless**: each run creates a fresh ephemeral
  sandbox (:func:`app.workflows.review.steps.create_sandbox.createSandboxStep`),
  clones the repo at review time, and destroys the sandbox in the
  ``finally`` (:func:`app.workflows.review.steps.kill_sandbox.killSandboxStep`).
- The ``review`` lifecycle row
  (:mod:`app.workflows.review.steps.review_lifecycle`) records one row
  per run: ``RUNNING`` once the PR row exists, ``SUCCESS`` after the
  GitHub post completes, ``FAILED`` on any terminal exception.
- GitHub posting is now **inline steps** (no separate post workflow):
  :func:`app.workflows.review.steps.post_review.postReviewStep` posts
  with its own retry policy (429 / 5xx retried without re-running the
  LLM) and terminal 4xx failures are returned as ``posted=False`` —
  the local review still completes.
- The comment-trigger path can set ``input.diffBaseSha`` to the last
  successfully reviewed head; ``fetchDiffStep`` then produces
  ``git diff {diffBaseSha}...{headSha}`` so an incremental re-review
  covers only the commits pushed since the previous run.
- The two research lanes run in parallel
  (:func:`app.workflows.review.steps.invoke_agent.invokeAgentStep`
  under ``asyncio.gather(return_exceptions=True)``); structured
  payloads are produced afterwards by the durable extractor steps.
- When OpenLLMetry telemetry is configured, the workflow is wrapped in
  a ``traceloop.sdk.decorators.workflow(name="review")`` span so every
  LLM call of the run nests under one per-review trace, tagged with
  the run's business context via
  :func:`Traceloop.set_association_properties` (see
  :mod:`app.core.telemetry`).
"""

from __future__ import annotations

import asyncio
import logging

from dbos import DBOS
from traceloop.sdk import Traceloop
from traceloop.sdk.decorators import workflow as traceloop_workflow

from app.models.enums import PRStatus
from app.services.sandbox.types import SandboxCtx
from app.utils.branded import (
    CommitId,
    InstallationId,
    PRNumber,
    PrRowId,
    RepoId,
    ReviewRowId,
    UserId,
)
from app.workflows.review.errors import (
    CloneError,
    ReviewAgentsError,
    ReviewStepFailure,
    SandboxCreateError,
)
from app.workflows.review.steps.clone_repo import cloneRepoStep
from app.workflows.review.steps.create_sandbox import createSandboxStep
from app.workflows.review.steps.extract_result import buildExtractorLlmCtx
from app.workflows.review.steps.fetch_diff import fetchDiffStep
from app.workflows.review.steps.get_repo import getRepoTx
from app.workflows.review.steps.invoke_agent import (
    combineLaneOutcomes,
    invokeAgentStep,
    runExtractorLanes,
)
from app.workflows.review.steps.kill_sandbox import killSandboxStep
from app.workflows.review.steps.persist import (
    persistCodeCommentsTx,
    persistReviewSummaryTx,
    persistReviewUsageTx,
    sumTotalUsages,
)
from app.workflows.review.steps.post_review import (
    postReviewStep,
    updatePostBacklinksTx,
)
from app.workflows.review.steps.review_lifecycle import (
    buildErrorContext,
    markReviewErroredStep,
    markReviewRunningStep,
    markReviewStoppedStep,
)
from app.workflows.review.steps.split_diff import splitDiffStep
from app.workflows.review.steps.upsert_pr import upsertPullRequestTx
from app.workflows.review.types import (
    PRSizeStats,
    RepoSnapshot,
    ReviewLimits,
    ReviewRunResult,
    ReviewWorkflowCtx,
    ReviewWorkflowInput,
)

log = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Pure workflow helpers                                                        #
# --------------------------------------------------------------------------- #


def createReviewWorkflowId(*, repoId: RepoId, prNumber: PRNumber, headSha: str) -> str:
    """Build the deterministic review workflow id.

    The id is the idempotency key: duplicate triggers for the same
    head SHA dedupe to the same DBOS workflow.
    """
    return f"review:{repoId}:{prNumber}:{headSha[:7]}"


_REVIEW_LIMIT_BASE = 150
_REVIEW_LIMIT_PER_FILE = 40
_REVIEW_LIMIT_PER_LINE = 0.25
_REVIEW_LIMIT_MIN = 150
_REVIEW_LIMIT_MAX = 2000


def computeReviewLimits(prSize: PRSizeStats) -> ReviewLimits:
    """Size the per-run agent call limits from the PR's size stats.

    The limit scales with the number of changed files and the total
    changed lines (``additions + deletions``), clamped to
    ``[_REVIEW_LIMIT_MIN, _REVIEW_LIMIT_MAX]`` so a huge PR cannot set
    an unbounded budget while a trivial PR still gets enough headroom
    to complete. The same ceiling applies to both the model-call and
    tool-call run limits.
    """
    files = prSize["changedFiles"]
    lines = prSize["additions"] + prSize["deletions"]
    work = files * _REVIEW_LIMIT_PER_FILE + lines * _REVIEW_LIMIT_PER_LINE
    limit = int(_REVIEW_LIMIT_BASE + work)
    limit = max(_REVIEW_LIMIT_MIN, min(_REVIEW_LIMIT_MAX, limit))
    return ReviewLimits(
        modelCallRunLimit=limit,
        toolCallRunLimit=limit,
    )


def buildReviewWorkflowInput(
    *,
    userId: UserId,
    ghRepoId: int,
    ghPrId: int,
    prNumber: PRNumber,
    baseBranch: str,
    defaultBranch: str | None,
    baseSha: str,
    headBranch: str,
    headSha: CommitId,
    author: str,
    title: str,
    body: str,
    status: PRStatus,
    prSize: PRSizeStats,
    githubInstallationId: InstallationId | None,
    postToGithub: bool,
    trigger: str = "opened",
    diffBaseSha: CommitId | None = None,
) -> ReviewWorkflowInput:
    """Assemble the PR-specific workflow input (for trigger adapters).

    Pure data transformation — the resolved run environment
    (:class:`LLMCtx` / :class:`SandboxCtx`) goes on the
    :class:`ReviewWorkflowCtx` built by the caller.
    """
    return ReviewWorkflowInput(
        userId=userId,
        ghRepoId=ghRepoId,
        ghPrId=ghPrId,
        prNumber=prNumber,
        baseBranch=baseBranch,
        defaultBranch=defaultBranch,
        baseSha=baseSha,
        headBranch=headBranch,
        headSha=headSha,
        author=author,
        title=title,
        body=body,
        status=status,
        trigger=trigger,
        postToGithub=postToGithub,
        githubInstallationId=githubInstallationId,
        prSize=prSize,
        diffBaseSha=diffBaseSha,
    )


# --------------------------------------------------------------------------- #
# The workflow                                                                 #
# --------------------------------------------------------------------------- #


@traceloop_workflow(name="review_workflow")
@DBOS.workflow()
async def reviewWorkflow(
    ctx: ReviewWorkflowCtx,
    input: ReviewWorkflowInput,
) -> ReviewRunResult:
    """Durable workflow: review one PR end-to-end.

    Body is a straight-line sequence of step calls. Steps raise on
    failure; transient ones are retried by DBOS via
    :func:`app.workflows.review.errors.shouldRetry`, business outcomes
    propagate and the DBOS workflow record is marked ERROR.

    The :func:`killSandboxStep` cleanup runs in a ``finally`` that
    covers every step after a successful
    :func:`createSandboxStep`. The ``review`` lifecycle row runs
    alongside: created in ``RUNNING`` after the PR row exists, flipped
    to ``SUCCESS`` by :func:`markReviewStoppedStep`, and flipped to
    ``FAILED`` by :func:`markReviewErroredStep` on any terminal
    exception (which is then re-raised).
    """

    workflow_id: str = DBOS.workflow_id or "<no-workflow-id>"

    repo: RepoSnapshot = await getRepoTx(ghRepoId=input.ghRepoId)

    # Tag every span of this run with the review's business context so
    # traces are filterable by repo / pr / head / user in the telemetry
    # backend. The @traceloop_workflow(name="review") wrapper above
    # carries these onto the workflow span; the parallel lane steps
    # inherit them via asyncio context propagation.
    Traceloop.set_association_properties(
        {
            "repo_id": repo.id,
            "pr_number": input.prNumber,
            "head_sha": input.headSha,
            "user_id": input.userId,
            "workflow_id": workflow_id,
        }
    )

    review_row_id: ReviewRowId | None = None
    sandbox_ctx: SandboxCtx = ctx.sandboxCtx

    try:
        sandbox_ctx = await createSandboxStep(sandbox_ctx)
        sandbox_id = sandbox_ctx.sandboxId
        if sandbox_id is None:
            raise ReviewStepFailure(
                SandboxCreateError(
                    message="create sandbox step returned no sandbox id",
                    userId=input.userId,
                    repoId=repo.id,
                    prNumber=input.prNumber,
                    headSha=input.headSha,
                )
            )

        if input.githubInstallationId is None:
            raise ReviewStepFailure(
                CloneError(
                    message="github installation id missing; cannot clone the repo",
                    userId=input.userId,
                    repoId=repo.id,
                    prNumber=input.prNumber,
                    headSha=input.headSha,
                )
            )

        await cloneRepoStep(
            sandboxCtx=sandbox_ctx,
            userId=input.userId,
            repoId=repo.id,
            repoOwner=repo.repoOwner,
            repoName=repo.repoName,
            prNumber=input.prNumber,
            githubInstallationId=input.githubInstallationId,
        )

        pr_row_id: PrRowId = await upsertPullRequestTx(repoId=repo.id, input=input)

        review_row_id = await markReviewRunningStep(
            userId=input.userId,
            repo=repo,
            input=input,
            prRowId=pr_row_id,
            sandboxId=sandbox_id,
            workflowId=workflow_id,
            llmProvider=ctx.llmCtx.origin,
            llmClient=ctx.llmCtx.provider,
            llmModel=ctx.llmCtx.modelId,
            llmBaseUrl=ctx.llmCtx.baseUrl,
        )

        await fetchDiffStep(
            sandboxCtx=sandbox_ctx,
            repoId=repo.id,
            repoName=repo.repoName,
            prNumber=input.prNumber,
            headSha=input.headSha,
            baseSha=input.baseSha,
            diffBaseSha=input.diffBaseSha,
        )

        await splitDiffStep(
            sandboxCtx=sandbox_ctx,
            repoId=repo.id,
            prNumber=input.prNumber,
            headSha=input.headSha,
        )

        limits = computeReviewLimits(input.prSize)

        agent_results = await asyncio.gather(
            invokeAgentStep(
                lane="summarizer",
                sandboxCtx=sandbox_ctx,
                llmCtx=ctx.llmCtx,
                repo=repo,
                input=input,
                limits=limits,
            ),
            invokeAgentStep(
                lane="comments",
                sandboxCtx=sandbox_ctx,
                llmCtx=ctx.llmCtx,
                repo=repo,
                input=input,
                limits=limits,
            ),
            return_exceptions=True,
        )

        lane_outcomes = await runExtractorLanes(
            agent_results,
            extractorLlmCtx=buildExtractorLlmCtx(),
        )

        combined = combineLaneOutcomes(
            lane_outcomes,
            prNumber=input.prNumber,
            headSha=input.headSha,
            repoId=repo.id,
            userId=input.userId,
        )

        if isinstance(combined, ReviewAgentsError):
            raise ReviewStepFailure(combined)

        review = combined.review
        usages = combined.usages

        summary_row_id = await persistReviewSummaryTx(
            prRowId=pr_row_id,
            reviewRowId=review_row_id,
            commitId=input.headSha,
            review=review,
        )

        comment_row_ids = await persistCodeCommentsTx(
            prRowId=pr_row_id,
            reviewRowId=review_row_id,
            commitId=input.headSha,
            comments=review.comments,
        )

        input_tokens, output_tokens, total_tokens, input_token_details = sumTotalUsages(
            usages
        )

        await persistReviewUsageTx(
            userId=input.userId,
            prRowId=pr_row_id,
            prNumber=input.prNumber,
            repoId=repo.id,
            reviewRowId=review_row_id,
            reviewSummaryId=summary_row_id,
            inputTokens=input_tokens,
            outputTokens=output_tokens,
            totalTokens=total_tokens,
            inputTokenDetails=input_token_details,
            llmModelId=ctx.llmCtx.modelId,
            llmProvider=ctx.llmCtx.provider,
            llmBaseUrl=ctx.llmCtx.baseUrl,
        )

        github_review_id: str | None = None
        if input.postToGithub:
            post_result = await postReviewStep(repo=repo, input=input, review=review)
            if post_result.posted and post_result.githubReviewId is not None:
                await updatePostBacklinksTx(
                    reviewRowId=review_row_id,
                    reviewSummaryId=str(summary_row_id),
                    commentRowIds=comment_row_ids,
                    githubReviewId=post_result.githubReviewId,
                    repoId=repo.id,
                    prNumber=input.prNumber,
                )
                github_review_id = str(post_result.githubReviewId)
            else:
                log.warning(
                    "review_workflow: github post failed (continuing): "
                    "workflow_id=%s pr_number=%s error=%s",
                    workflow_id,
                    input.prNumber,
                    post_result.error,
                )

        await markReviewStoppedStep(
            reviewRowId=review_row_id,
            commentCount=len(review.comments),
            githubReviewId=github_review_id,
            userId=input.userId,
            repoId=repo.id,
        )

        log.info(
            "review_workflow: stopping workflow: workflow_id=%s "
            "gh_repo_id=%s number=%s head_sha=%s",
            workflow_id,
            input.ghRepoId,
            input.prNumber,
            input.headSha,
        )

        return ReviewRunResult(
            prRowId=pr_row_id,
            commitId=input.headSha,
            review=review,
            usages=usages,
        )

    except BaseException as exc:
        try:
            await markReviewErroredStep(
                reviewRowId=review_row_id,
                errorName=type(exc).__name__,
                errorMessage=str(exc),
                errorContext=buildErrorContext(exc),
                userId=input.userId,
                repoId=repo.id,
            )
        except Exception:
            log.exception(
                "review_workflow: failed to record review error "
                "review_id=%s workflow_id=%s",
                review_row_id,
                workflow_id,
            )
        raise

    finally:
        if sandbox_ctx.sandboxId is not None:
            await killSandboxStep(sandboxCtx=sandbox_ctx)


__all__ = [
    "buildReviewWorkflowInput",
    "computeReviewLimits",
    "createReviewWorkflowId",
    "reviewWorkflow",
]
