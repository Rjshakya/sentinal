"""Agent-phase steps: planner, file batches, extract, summary.

Degrade steps catch final ReviewStepFailure inside and return the
degraded value; transient failures propagate for SDK retry. Imports
on top.
"""

from __future__ import annotations

import asyncio
import logging

from aws_durable_execution_sdk_python import durable_step
from aws_durable_execution_sdk_python.types import StepContext
from pydantic import BaseModel, ConfigDict

from app.services.agent_v2.types import (
    ChunkInventory,
    FileReviewJob,
    PlannerContext,
)
from app.services.llm.types import LLMCtx
from app.services.sandbox.types import SandboxCtx
from app.utils.branded import RepoId
from app.utils.schema import ReviewComments
from app.workflows.review_v2.errors import (
    ReviewStepFailure,
    TransientReviewStepFailure,
)
from app.workflows.review_v2.steps.extract_result import (
    buildExtractorLlmCtx,
    extractCommentsStep,
)
from app.workflows.review_v2.steps.invoke_file import invokeFileReviewStep
from app.workflows.review_v2.steps.invoke_planner import getPlanStep, invokePlannerStep
from app.workflows.review_v2.steps.synthesize_summary import synthesizeSummaryStep
from app.workflows.review_v2.types import (
    RepoSnapshot,
    ReviewLimits,
    ReviewWorkflowInput,
)

log = logging.getLogger(__name__)


def usageToJson(usage: object) -> dict:
    out: dict = {}
    items = dict(usage or {}).items() if isinstance(usage, dict) else []
    for model_name, meta in items:
        get = meta.get if isinstance(meta, dict) else lambda k, d=None: getattr(meta, k, d)
        details = get("input_token_details") or {}
        dget = details.get if isinstance(details, dict) else lambda k, d=None: getattr(details, k, d)
        out[str(model_name)] = {
            "input_tokens": get("input_tokens") or 0,
            "output_tokens": get("output_tokens") or 0,
            "total_tokens": get("total_tokens") or 0,
            "input_token_details": {
                "cache_read": dget("cache_read"),
                "cache_creation": dget("cache_creation"),
            },
        }
    return out


class PlannerInput(BaseModel):
    model_config = ConfigDict(frozen=True)

    sandbox: SandboxCtx
    llm: LLMCtx
    repo: RepoSnapshot
    workflowInput: ReviewWorkflowInput
    actualFiles: list[str]
    limits: ReviewLimits


@durable_step
def runPlanner(_ctx: StepContext, *, input: dict) -> dict:
    """Run the planning agent; degrades to empty usage on final failure."""
    request = PlannerInput.model_validate(input)
    try:
        usage = asyncio.run(
            invokePlannerStep(
                sandboxCtx=request.sandbox,
                llmCtx=request.llm,
                repo=request.repo,
                input=request.workflowInput,
                actualFiles=list(request.actualFiles),
                limits=request.limits,
            )
        )
    except ReviewStepFailure as exc:
        log.warning("runPlanner: degraded to empty context: %s", exc)
        return {
            "usage": {},
            "degraded": True,
            "empty_context": PlannerContext().model_dump(mode="json"),
        }
    return {"usage": usageToJson(usage), "degraded": False}


class PlanReadInput(BaseModel):
    model_config = ConfigDict(frozen=True)

    sandbox: SandboxCtx
    repoId: RepoId
    workflowInput: ReviewWorkflowInput


@durable_step
def readPlannerOutput(_ctx: StepContext, *, input: dict) -> dict:
    """Read plan.json; None means the planner never submitted."""
    request = PlanReadInput.model_validate(input)
    try:
        plan = asyncio.run(
            getPlanStep(
                sandboxCtx=request.sandbox,
                repoId=request.repoId,
                input=request.workflowInput,
            )
        )
    except ReviewStepFailure as exc:
        log.warning("readPlannerOutput: no usable plan: %s", exc)
        return {"planner_context": None}
    return {"planner_context": plan.model_dump(mode="json")}


class FileBatchInput(BaseModel):
    model_config = ConfigDict(frozen=True)

    sandbox: SandboxCtx
    llm: LLMCtx
    repo: RepoSnapshot
    workflowInput: ReviewWorkflowInput
    limits: ReviewLimits
    jobs: list[FileReviewJob]
    sharedConcerns: str


@durable_step
def runFileBatch(_ctx: StepContext, *, input: dict) -> dict:
    """Review one batch of files; per-file failures degrade to nothing."""
    request = FileBatchInput.model_validate(input)

    async def run() -> dict:
        reports: dict[str, str] = {}
        failed: list[str] = []
        usages: dict[str, dict] = {}
        for job in request.jobs:
            text: str | None = None
            usage: object = {}
            attempts = 0
            while attempts < 2 and text is None:
                attempts += 1
                try:
                    text, usage = await invokeFileReviewStep(
                        filePath=job.filePath,
                        job=job,
                        sharedConcerns=request.sharedConcerns,
                        sandboxCtx=request.sandbox,
                        llmCtx=request.llm,
                        repo=request.repo,
                        input=request.workflowInput,
                        limits=request.limits,
                        rateLimiterKey=None,
                    )
                except TransientReviewStepFailure as exc:
                    log.warning(
                        "runFileBatch: transient file=%s attempt=%d: %s",
                        job.filePath,
                        attempts,
                        exc,
                    )
                    if attempts >= 2:
                        failed.append(job.filePath)
                except (ReviewStepFailure, Exception) as exc:
                    log.warning(
                        "runFileBatch: failed file=%s: %s: %s",
                        job.filePath,
                        type(exc).__name__,
                        exc,
                    )
                    failed.append(job.filePath)
                    break
            if text is not None:
                reports[job.filePath] = text
                usages[job.filePath] = usageToJson(usage)
        return {"reports": reports, "failed": failed, "usages": usages}

    return asyncio.run(run())


@durable_step
def extractReviewComments(_ctx: StepContext, *, rawText: str) -> dict:
    """Transcribe concatenated file reports into comment drafts."""
    comments, usage = asyncio.run(
        extractCommentsStep(
            extractorLlmCtx=buildExtractorLlmCtx(), rawText=rawText
        )
    )
    return {
        "comments": comments.model_dump(mode="json").get("List", []),
        "usage": usageToJson(usage),
    }


class SummaryInput(BaseModel):
    model_config = ConfigDict(frozen=True)

    workflowInput: ReviewWorkflowInput
    repo: RepoSnapshot
    inventory: ChunkInventory
    plannerContext: PlannerContext
    comments: ReviewComments


@durable_step
def synthesizeWalkthrough(_ctx: StepContext, *, input: dict) -> dict:
    """Synthesize the walkthrough; degrades to empty string."""
    request = SummaryInput.model_validate(input)
    try:
        summary, usage = asyncio.run(
            synthesizeSummaryStep(
                input=request.workflowInput,
                repo=request.repo,
                inventory=request.inventory,
                plannerContext=request.plannerContext,
                comments=request.comments,
            )
        )
    except ReviewStepFailure as exc:
        log.warning("synthesizeWalkthrough: degraded to empty: %s", exc)
        return {"summary": "", "usage": {}}
    return {"summary": summary.summary, "usage": usageToJson(usage)}


__all__ = [
    "extractReviewComments",
    "readPlannerOutput",
    "runFileBatch",
    "runPlanner",
    "synthesizeWalkthrough",
]
