"""V2 review durable workflow: planner + per-file agents.

The isolated successor of :func:`app.workflows.review.workflow.reviewWorkflow`
(same infra, new agent phase — the v1 workflow is untouched and keeps
serving traffic until an explicit future swap):

1. Infra: resolve repo → create ephemeral sandbox → v2 clone
   (default-branch clone + PR-ref fetch + detached head checkout,
   atomically; any checkout refusal fails the run) → upsert PR →
   mark ``RUNNING`` → fetch diff → split diff.
2. :func:`app.workflows.review_v2.steps.list_chunks.listChunkFilesStep`
   inventories ``splitted_diffs/`` — the host-side diff truth that
   drives the fan-out.
3. :func:`invokePlannerStep` + :func:`getPlanStep` produce the
   :class:`PlannerContext` (enrichment only — a failure degrades to
   an empty context, never fails the run).
4. The pure :func:`buildFileReviewJobs` join attaches planner context
   to inventory files (trivial files dropped host-side).
5. One :func:`invokeFileReviewStep` per job, fanned out in sequential
   batches of :data:`V2_FANOUT_BATCH_SIZE` via
   ``asyncio.gather(return_exceptions=True)``. Each file retries
   alone; failed files degrade to nothing.
6. The surviving raw reports are concatenated and transcribed once by
   the shared :func:`extractCommentsStep`; the merged review +
   usage envelope is built by :func:`combineV2Reports`.
7. Persist (summary / comments / usage), inline GitHub post, mark
   ``SUCCESS`` / ``FAILED``, destroy the sandbox in ``finally``.

- All workflow inputs and outputs are the v1 Pydantic models
  (:class:`ReviewWorkflowCtx` / :class:`ReviewWorkflowInput` /
  :class:`ReviewRunResult`) so DBOS serialisation and the
  persistence layer behave identically.
- The sandbox object is never passed between steps — only the
  :class:`SandboxCtx` travels; each step reconnects by id.
- Deterministic workflow id ``review-v2:{repo_id}:{pr}:{head_sha[:7]}``
  (distinct namespace from v1, so v2 eval runs never collide with
  production v1 runs).
"""

from __future__ import annotations

import asyncio
import logging

from dbos import DBOS
from langchain_core.messages import UsageMetadata
from traceloop.sdk import Traceloop
from traceloop.sdk.decorators import workflow as traceloop_workflow

from app.services.agent_v2.types import PlannerContext
from app.services.llm.service import acquireSharedLimiter, releaseSharedLimiter
from app.services.sandbox.types import SandboxCtx
from app.utils.branded import PRNumber, PrRowId, RepoId, ReviewRowId
from app.utils.schema import ReviewComments
from app.workflows.review.errors import (
    CloneError,
    ReviewStepFailure,
    SandboxCreateError,
)
from app.workflows.review.steps.create_sandbox import createSandboxStep
from app.workflows.review.steps.extract_result import (
    buildExtractorLlmCtx,
    extractCommentsStep,
)
from app.workflows.review.steps.fetch_diff import fetchDiffStep
from app.workflows.review.steps.get_repo import getRepoTx
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
    RepoSnapshot,
    ReviewLimits,
    ReviewRunResult,
    ReviewWorkflowCtx,
    ReviewWorkflowInput,
)
from app.workflows.review_v2.errors import V2AgentsError
from app.workflows.review_v2.steps.combine import (
    buildFileReviewJobs,
    chunkedJobs,
    coerceFileLaneError,
    combineV2Reports,
    concatFileReports,
)
from app.workflows.review_v2.steps.clone_repo_v2 import cloneRepoV2Step
from app.workflows.review_v2.steps.invoke_file import invokeFileReviewStep
from app.workflows.review_v2.steps.invoke_planner import (
    getPlanStep,
    invokePlannerStep,
)
from app.workflows.review_v2.steps.list_chunks import listChunkFilesStep
from app.workflows.review_v2.steps.synthesize_summary import synthesizeSummaryStep

log = logging.getLogger(__name__)


def createReviewV2WorkflowId(
    *, repoId: RepoId, prNumber: PRNumber, headSha: str
) -> str:
    """Build the deterministic v2 review workflow id.

    The id is the idempotency key: duplicate triggers for the same
    head SHA dedupe to the same DBOS workflow. The ``review-v2:``
    namespace keeps v2 runs distinct from v1 ``review:`` runs.
    """
    return f"review-v2:{repoId}:{prNumber}:{headSha[:7]}"


_PLANNER_MODEL_CALL_LIMIT = 200
_PLANNER_TOOL_CALL_LIMIT = 200
_FILE_MODEL_CALL_LIMIT = 100
_FILE_TOOL_CALL_LIMIT = 100


def _plannerLimits() -> ReviewLimits:
    """Fixed per-run call limits for the planning agent."""
    return ReviewLimits(
        modelCallRunLimit=_PLANNER_MODEL_CALL_LIMIT,
        toolCallRunLimit=_PLANNER_TOOL_CALL_LIMIT,
    )


def _fileLimits() -> ReviewLimits:
    """Fixed per-file call limits for one file-review agent.

    Each agent sees a single chunk, so a small fixed budget keeps
    cost linear in files without PR-size plumbing.
    """
    return ReviewLimits(
        modelCallRunLimit=_FILE_MODEL_CALL_LIMIT,
        toolCallRunLimit=_FILE_TOOL_CALL_LIMIT,
    )


@traceloop_workflow(name="review_v2_workflow")
@DBOS.workflow()
async def reviewWorkflowV2(
    ctx: ReviewWorkflowCtx,
    input: ReviewWorkflowInput,
) -> ReviewRunResult:
    """Durable workflow: review one PR end-to-end (v2 agent phase).

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
    # backend, distinguishable from v1 by the workflow span name.
    Traceloop.set_association_properties(
        {
            "repo_id": repo.id,
            "pr_number": input.prNumber,
            "head_sha": input.headSha,
            "user_id": input.userId,
            "workflow_id": workflow_id,
            "workflow_version": "v2",
        }
    )

    review_row_id: ReviewRowId | None = None
    sandbox_ctx: SandboxCtx = ctx.sandboxCtx

    try:

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

        # V2-native clone: default-branch clone + PR-ref fetch +
        # detached head checkout in one atomic script. Fail-closed:
        # any checkout refusal raises and fails the run — v2 never
        # reviews a half-built tree.
        cloneResult = await cloneRepoV2Step(
            sandboxCtx=sandbox_ctx,
            userId=input.userId,
            repoId=repo.id,
            repoOwner=repo.repoOwner,
            repoName=repo.repoName,
            prNumber=input.prNumber,
            headSha=input.headSha,
            githubInstallationId=input.githubInstallationId,
        )
        log.info(
            "review_v2: repo ready: workflow_id=%s checked_out_head=%s",
            workflow_id,
            cloneResult.checkedOutHead,
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

        inventory = await listChunkFilesStep(
            sandboxCtx=sandbox_ctx,
            repoId=repo.id,
            prNumber=input.prNumber,
            headSha=input.headSha,
        )

        # --- Planner phase (enrichment-only; degrades, never fails) ---
        plannerContext = PlannerContext()
        plannerUsage: dict[str, UsageMetadata] = {}
        plannerDegraded = False
        if inventory.actualFiles:
            try:
                plannerUsage = await invokePlannerStep(
                    sandboxCtx=sandbox_ctx,
                    llmCtx=ctx.llmCtx,
                    repo=repo,
                    input=input,
                    actualFiles=inventory.actualFiles,
                    limits=_plannerLimits(),
                )
                try:
                    plannerContext = await getPlanStep(
                        sandboxCtx=sandbox_ctx,
                        repoId=repo.id,
                        input=input,
                    )
                except BaseException as exc:
                    plannerDegraded = True
                    log.warning(
                        "review_v2: plan read degraded "
                        "(continuing without planner context): "
                        "workflow_id=%s cause=%s: %s",
                        workflow_id,
                        type(exc).__name__,
                        exc,
                    )
            except BaseException as exc:
                plannerDegraded = True
                log.warning(
                    "review_v2: planner degraded "
                    "(continuing without planner context): "
                    "workflow_id=%s cause=%s: %s",
                    workflow_id,
                    type(exc).__name__,
                    exc,
                )
        else:
            log.info(
                "review_v2: no reviewable chunks (workflow_id=%s); "
                "skipping agent phase",
                workflow_id,
            )

        built = buildFileReviewJobs(
            inventory=inventory,
            plannerContext=plannerContext,
        )
        if built.ignoredPlannerFiles:
            log.warning(
                "review_v2: planner mentioned %d unknown file(s), ignored: %s",
                len(built.ignoredPlannerFiles),
                built.ignoredPlannerFiles,
            )
        if built.skippedUnpairedFiles:
            log.warning(
                "review_v2: %d inventoried file(s) had no observed chunk, skipped: %s",
                len(built.skippedUnpairedFiles),
                built.skippedUnpairedFiles,
            )
        jobs = built.jobs
        log.info(
            "review_v2: fanning out to %d file agent(s) "
            "(planner_degraded=%s missing_context=%d)",
            len(jobs),
            plannerDegraded,
            sum(1 for job in jobs if not job.hasPlannerContext),
        )

        # --- Per-file fan-out: sequential batches of concurrent lanes ---
        # One wave shares ONE rate limiter (acquired per wave, released
        # right after), so the wave's agents draw from a single smoothed
        # budget instead of bursting through independent per-step ones.
        # The shared budget scales with wave width to preserve
        # per-agent-equivalent throughput — sharing the raw configured
        # rate would serialize the whole wave through it.
        reportsByFile: dict[str, str] = {}
        researchUsages: dict[str, dict[str, UsageMetadata]] = {}
        succeededFiles: list[str] = []
        failedOutcomes: list[tuple[str, BaseException]] = []
        for batchIndex, batch in enumerate(chunkedJobs(jobs)):
            llmRps = ctx.llmCtx.rateLimitRps
            rateLimiterKey: str | None = None
            if llmRps is not None and llmRps > 0:
                rateLimiterKey = f"{workflow_id}:batch-{batchIndex}"
                acquireSharedLimiter(
                    key=rateLimiterKey,
                    requestsPerSecond=llmRps * len(batch),
                )
            try:
                batchResults = await asyncio.gather(
                    *(
                        invokeFileReviewStep(
                            filePath=job.filePath,
                            job=job,
                            sharedConcerns=plannerContext.sharedConcerns,
                            sandboxCtx=sandbox_ctx,
                            llmCtx=ctx.llmCtx,
                            repo=repo,
                            input=input,
                            limits=_fileLimits(),
                            rateLimiterKey=rateLimiterKey,
                        )
                        for job in batch
                    ),
                    return_exceptions=True,
                )
            finally:
                if rateLimiterKey is not None:
                    releaseSharedLimiter(key=rateLimiterKey)
            for job, outcome in zip(batch, batchResults):
                if isinstance(outcome, BaseException):
                    failedOutcomes.append((job.filePath, outcome))
                    continue
                text, usage = outcome
                reportsByFile[job.filePath] = text
                researchUsages[job.filePath] = usage
                succeededFiles.append(job.filePath)

        failedFiles = [file for file, _ in failedOutcomes]
        if failedFiles:
            log.warning(
                "review_v2: %d/%d file lane(s) failed: %s",
                len(failedFiles),
                len(jobs),
                [
                    (file, coerceFileLaneError(exc, file).message)
                    for file, exc in failedOutcomes
                ],
            )

        if jobs and not succeededFiles:
            raise ReviewStepFailure(
                V2AgentsError(
                    message=(
                        f"v2 review agents failed for pr={input.prNumber} "
                        f"head_sha={input.headSha[:7]}: failed={failedFiles}"
                    ),
                    userId=input.userId,
                    repoId=repo.id,
                    prNumber=input.prNumber,
                    headSha=input.headSha,
                    failedFiles=[
                        coerceFileLaneError(exc, file) for file, exc in failedOutcomes
                    ],
                    succeededFiles=[],
                    plannerDegraded=plannerDegraded,
                )
            )

        mergedReport = concatFileReports(reportsByFile)
        if mergedReport.strip():
            extractedComments, _ = await extractCommentsStep(
                extractorLlmCtx=buildExtractorLlmCtx(),
                rawText=mergedReport,
            )
            comments = extractedComments
        else:
            comments = ReviewComments(List=[])

        # --- Summary synthesis (degrades to empty, never fails the run) ---
        summaryMarkdown = ""
        summaryUsage: dict[str, UsageMetadata] | None = None
        try:
            synthesized, synthUsage = await synthesizeSummaryStep(
                input=input,
                repo=repo,
                inventory=inventory,
                plannerContext=plannerContext,
                comments=comments,
            )
            summaryMarkdown = synthesized.summary
            summaryUsage = synthUsage
        except BaseException as exc:
            log.warning(
                "review_v2: summary degraded "
                "(continuing with empty summary): "
                "workflow_id=%s cause=%s: %s",
                workflow_id,
                type(exc).__name__,
                exc,
            )

        combined = combineV2Reports(
            comments=comments,
            summaryMarkdown=summaryMarkdown,
            researchUsages=researchUsages,
            plannerUsage=plannerUsage or None,
            summaryUsage=summaryUsage,
            prNumber=input.prNumber,
            headSha=input.headSha,
            repoId=repo.id,
            userId=input.userId,
        )

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
                    "review_v2: github post failed (continuing): "
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
            "review_v2: stopping workflow: workflow_id=%s "
            "gh_repo_id=%s number=%s head_sha=%s files=%d comments=%d",
            workflow_id,
            input.ghRepoId,
            input.prNumber,
            input.headSha,
            len(succeededFiles),
            len(review.comments),
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
                "review_v2: failed to record review error "
                "review_id=%s workflow_id=%s",
                review_row_id,
                workflow_id,
            )
        raise

    finally:
        if sandbox_ctx.sandboxId is not None:
            await killSandboxStep(sandboxCtx=sandbox_ctx)


__all__ = [
    "createReviewV2WorkflowId",
    "reviewWorkflowV2",
]
