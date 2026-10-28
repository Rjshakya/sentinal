"""Run review + summary pi agents in parallel from one plan path.

``runReviewer`` takes the validated ``PlanFilePath`` and fans out two
``pi --print`` runs — ``…-review`` (writes ``review.jsonl``) and
``…-summary`` (writes ``summary.jsonl``) — over two independent
backend reconnects via ``asyncio.gather``. Both prompts name the plan
path; the agent reads it from disk. The host validates both outputs
into one :class:`Review`: review-lane failure fails the step,
summary-lane failure degrades to an empty summary with a recomputed
verdict, and the summed phase costs ride on the returned value.
"""

from __future__ import annotations

import asyncio
import json
import shlex
from typing import Any

from app.services.llm_config.types import LLMConfigCtx
from app.services.pi_harness.cost import addTotalCosts, getPiSessionCost
from app.services.pi_harness.errors import PiCostError
from app.services.pi_harness.harness import PiAgentHarness, modelFromCtx, phaseSessionId
from app.services.pi_harness.types import PiModel, PiRunResult
from app.services.sandbox.errors import SandboxProviderError
from app.services.sandbox.service import getProvider
from app.services.sandbox.types import BaseSandbox, SandboxCtx
from app.utils.branded import CommitId, PRNumber
from app.utils.sandbox_fs import getReviewFile, getSummaryFile
from app.workflows.review_v3.errors import ReviewerError
from app.workflows.review_v3.types import (
    PlanFilePath,
    Review,
    ReviewComment,
    ReviewFile,
    SummaryFile,
    verdictFor,
)

_RUN_TIMEOUT_S = 600
_READ_TIMEOUT_S = 60
_ERROR_CHARS = 500


def _parseSummaryFile(text: str) -> str | ReviewerError:
    """Validate ``summary.jsonl`` into its markdown (pure)."""
    try:
        data: Any = json.loads(text)
    except Exception as exc:
        return ReviewerError(
            message=f"summary file is not JSON: {type(exc).__name__}: {exc}"
        )
    if not isinstance(data, dict):
        return ReviewerError(message="summary file is not a JSON object")
    try:
        return SummaryFile.model_validate(data).summary
    except Exception as exc:
        return ReviewerError(
            message=f"summary file invalid: {type(exc).__name__}: {exc}"
        )


def _parseReviewFile(text: str) -> list[ReviewComment] | ReviewerError:
    """Validate ``review.jsonl`` into its findings (pure)."""
    try:
        data: Any = json.loads(text)
    except Exception as exc:
        return ReviewerError(
            message=f"review file is not JSON: {type(exc).__name__}: {exc}"
        )
    if not isinstance(data, dict):
        return ReviewerError(message="review file is not a JSON object")
    try:
        return ReviewFile.model_validate(data).comments
    except Exception as exc:
        return ReviewerError(
            message=f"review file invalid: {type(exc).__name__}: {exc}"
        )


async def _execLane(
    *,
    sandboxCtx: SandboxCtx,
    model: PiModel,
    sessionId: str,
    prompt: str,
    systemPrompts: list[str],
    runTimeoutS: int,
) -> PiRunResult | ReviewerError:
    """Reconnect and run one pi lane; failures fold into values."""
    try:
        provider = getProvider(sandboxCtx.providerId)
    except Exception as exc:
        return ReviewerError(
            message=f"unknown sandbox provider: {type(exc).__name__}: {exc}",
            retryable=True,
        )
    try:
        made = await provider(ctx=sandboxCtx).create()
    except Exception as exc:
        return ReviewerError(
            message=f"sandbox reconnect raised {type(exc).__name__}: {exc}",
            retryable=True,
        )
    if isinstance(made, SandboxProviderError):
        return ReviewerError(
            message=f"sandbox reconnect failed: {made.message}", retryable=True
        )
    harness = PiAgentHarness(sessionId=sessionId, model=model)
    for systemPrompt in systemPrompts:
        harness.appendSystemPrompt(systemPrompt)
    try:
        return await harness.run(prompt, made, timeoutS=runTimeoutS)
    except Exception as exc:
        return ReviewerError(
            message=f"pi run raised {type(exc).__name__}: {exc}", retryable=True
        )


async def _readFile(
    backend: BaseSandbox, *, path: str, label: str
) -> str | ReviewerError:
    """Cat one sandbox file; missing/empty folds into an error value."""
    try:
        read = await backend.aexecute(
            f"cat {shlex.quote(path)}", timeout=_READ_TIMEOUT_S
        )
    except Exception as exc:
        return ReviewerError(
            message=f"{label} read raised {type(exc).__name__}: {exc}",
            retryable=True,
        )
    if read.exit_code != 0:
        return ReviewerError(
            message=f"{label} file missing: {read.output.strip()[-_ERROR_CHARS:]}"
        )
    if not read.output.strip():
        return ReviewerError(message=f"{label} file is empty")
    return read.output


async def runReviewer(
    *,
    planPath: PlanFilePath,
    sandboxCtx: SandboxCtx,
    llm: LLMConfigCtx,
    prNumber: PRNumber,
    headSha: CommitId,
    reviewPrompt: str,
    summaryPrompt: str,
    systemPrompts: list[str] | None = None,
    runTimeoutS: int = _RUN_TIMEOUT_S,
) -> Review | ReviewerError:
    """Run review + summary lanes from the plan path; merge into a Review."""
    if not str(planPath).strip():
        raise ValueError("planPath must be non-empty")
    if not reviewPrompt.strip():
        raise ValueError("reviewPrompt must be non-empty")
    if not summaryPrompt.strip():
        raise ValueError("summaryPrompt must be non-empty")
    model = modelFromCtx(llm)
    extraPrompts = list(systemPrompts or [])
    pr = int(prNumber)
    sha = str(headSha)
    reviewSid = phaseSessionId(prNumber=pr, headSha=sha, phase="review")
    summarySid = phaseSessionId(prNumber=pr, headSha=sha, phase="summary")
    planSid = phaseSessionId(prNumber=pr, headSha=sha, phase="plan")

    try:
        reviewRes, summaryRes = await asyncio.gather(
            _execLane(
                sandboxCtx=sandboxCtx,
                model=model,
                sessionId=reviewSid,
                prompt=f"Read the plan at {planPath} first. {reviewPrompt}",
                systemPrompts=extraPrompts,
                runTimeoutS=runTimeoutS,
            ),
            _execLane(
                sandboxCtx=sandboxCtx,
                model=model,
                sessionId=summarySid,
                prompt=f"Read the plan at {planPath} first. {summaryPrompt}",
                systemPrompts=extraPrompts,
                runTimeoutS=runTimeoutS,
            ),
        )
    except Exception as exc:
        return ReviewerError(
            message=f"review gather raised {type(exc).__name__}: {exc}",
            retryable=True,
        )

    if isinstance(reviewRes, ReviewerError):
        return reviewRes
    if not reviewRes.ok:
        return ReviewerError(
            message=f"review run failed: {reviewRes.error or 'unknown error'}"
        )

    try:
        provider = getProvider(sandboxCtx.providerId)
    except Exception as exc:
        return ReviewerError(
            message=f"unknown sandbox provider: {type(exc).__name__}: {exc}",
            retryable=True,
        )
    try:
        made = await provider(ctx=sandboxCtx).create()
    except Exception as exc:
        return ReviewerError(
            message=f"sandbox reconnect raised {type(exc).__name__}: {exc}",
            retryable=True,
        )
    if isinstance(made, SandboxProviderError):
        return ReviewerError(
            message=f"sandbox reconnect failed: {made.message}", retryable=True
        )
    backend: BaseSandbox = made

    reviewText = await _readFile(
        backend, path=getReviewFile(sha), label="review output"
    )
    if isinstance(reviewText, ReviewerError):
        return reviewText
    comments = _parseReviewFile(reviewText)
    if isinstance(comments, ReviewerError):
        return comments

    summaryText = ""
    if not isinstance(summaryRes, ReviewerError) and summaryRes.ok:
        found = await _readFile(
            backend, path=getSummaryFile(sha), label="summary output"
        )
        if not isinstance(found, ReviewerError):
            parsed = _parseSummaryFile(found)
            if not isinstance(parsed, ReviewerError):
                summaryText = parsed

    planCost = await getPiSessionCost(made, sessionId=planSid)
    if isinstance(planCost, PiCostError):
        return ReviewerError(message=f"plan cost read failed: {planCost.message}")
    reviewCost = await getPiSessionCost(made, sessionId=reviewSid)
    if isinstance(reviewCost, PiCostError):
        return ReviewerError(message=f"review cost read failed: {reviewCost.message}")
    summaryCost = await getPiSessionCost(made, sessionId=summarySid)
    if isinstance(summaryCost, PiCostError):
        return ReviewerError(
            message=f"summary cost read failed: {summaryCost.message}"
        )

    return Review(
        summary=summaryText,
        verdict=verdictFor(comments),
        comments=comments,
        cost=addTotalCosts([planCost, reviewCost, summaryCost]),
    )


__all__ = ["runReviewer"]
