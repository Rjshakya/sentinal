"""DBOS durable steps that run the review agents.

One parameterized lane step (:func:`invokeAgentStep`) runs both
research agents — the workflow starts it twice from the workflow body
via ``asyncio.gather(..., return_exceptions=True)`` (the documented
DBOS parallel-steps pattern; deterministic start order). Each lane:

1. builds its chat model from the run's :class:`LLMCtx`
   (:func:`app.services.llm.service.createLLMModel`),
2. assembles a :class:`ReviewAgentCtx`
   (:func:`app.services.agent.service.createReviewAgentCtx`) with the
   lane's model + the shared sandbox handle,
3. builds the research agent (:func:`createSummaryAgent` /
   :func:`createCommentsAgent`) and runs it with the shared user
   prompt, capturing token usage.

A transient failure (LLM 429 / 5xx / timeout, sandbox blip) retries
**that lane alone** (the step edge raises
:class:`TransientReviewStepFailure`); a final failure raises
:class:`ReviewStepFailure`. With ``return_exceptions=True`` the raised
exceptions land in the gather results, so
:func:`combineLaneOutcomes` can partition them:

- both lanes failed → :class:`ReviewAgentsError` (the workflow raises
  it wrapped, marking the run ERROR),
- partial failure → the failed lane degrades to an empty default and
  the review completes with the successful lane's output.

Token usage is aggregated from the successful lanes only. The invoke
steps never stop the sandbox — the workflow's ``finally``
(:func:`app.workflows.review.steps.kill_sandbox.killSandboxStep`)
owns the stop.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any, Literal, TypedDict

from dbos import DBOS
from langchain_core.callbacks import get_usage_metadata_callback
from langchain_core.messages import UsageMetadata
from pydantic import BaseModel

from app.services.agent.errors import AgentBuildError
from app.services.agent.service import (
    combineReviewResults,
    createCommentsAgent,
    createReviewAgentCtx,
    createSummaryAgent,
    createUserPrompt,
)
from app.services.agent.types import DeepAgentGraph
from app.services.llm.errors import LLMConfigError
from app.services.llm.service import createLLMModel
from app.services.llm.types import LLMCtx
from app.services.sandbox.errors import SandboxProviderError
from app.services.sandbox.types import SandboxCtx
from app.utils.branded import CommitId, PRNumber, RepoId, UserId
from app.utils.schema import ReviewComments, ReviewResult, SummaryResult
from app.workflows.review.errors import (
    AgentLane,
    AgentLaneError,
    ReviewAgentsError,
    ReviewStepError,
    ReviewStepFailure,
    TransientReviewStepFailure,
    isLlmRetryError,
    shouldRetry,
)
from app.workflows.review.steps.extract_result import (
    extractCommentsStep,
    extractSummaryStep,
)
from app.workflows.review.types import (
    InputTokenDetails,
    RepoSnapshot,
    ReviewLimits,
    ReviewWorkflowInput,
    TotalUsages,
    TotalUsagesPerPR,
)

log = logging.getLogger(__name__)

AGENT_LANES: tuple[Literal["summarizer"], Literal["comments"]] = (
    "summarizer",
    "comments",
)
"""The two lane names, in the deterministic gather order."""

AgentStepOutcome = tuple[str, dict[str, UsageMetadata]] | BaseException
"""Outcome of one research-agent step: ``(raw_text, usage)`` or an
exception (a wrapped :class:`AgentLaneError`)."""

ExtractedSummary = tuple[SummaryResult, dict[str, UsageMetadata]]
"""Successful summarizer extractor result: the payload plus token usage."""

ExtractedComments = tuple[ReviewComments, dict[str, UsageMetadata]]
"""Successful comments extractor result: the payload plus token usage."""

SummaryLaneOutcome = ExtractedSummary | BaseException
"""Final summarizer lane outcome: extracted payload or a lane failure."""

CommentsLaneOutcome = ExtractedComments | BaseException
"""Final comments lane outcome: extracted payload or a lane failure."""


class ExtractorLaneResults(TypedDict):
    """Per-lane outcomes of the research + extraction fan-out.

    Each value is either the lane's validated structured payload with
    its token usage (the research agent's usage; the extractor step's
    own tokens are not yet accounted) or a ``BaseException`` — a
    wrapped :class:`AgentLaneError` from the research or extractor
    step.
    """

    summarizer: SummaryLaneOutcome
    comments: CommentsLaneOutcome


class CombinedReview(BaseModel):
    """The merged review payload plus the per-run usage envelope."""

    review: ReviewResult
    usages: TotalUsagesPerPR


# Defaults for failed lanes: an empty summary string and an empty
# comment list. The summary column is non-null, so an empty string is
# valid; the review body then carries no summary text for that run.
_DEFAULT_SUMMARY: str = ""


def _lastAiText(result: Any) -> str:
    """Return the text content of the last AI message in the run result."""
    if not isinstance(result, dict):
        return ""
    messages = result.get("messages")
    if not isinstance(messages, list):
        return ""
    for message in reversed(messages):
        if getattr(message, "type", None) != "ai":
            continue
        content = getattr(message, "content", None)
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts = [
                block.get("text", "")
                for block in content
                if isinstance(block, dict) and block.get("type") == "text"
            ]
            if parts:
                return "".join(parts)
    return ""


def _laneError(failure: BaseException, lane: AgentLane) -> AgentLaneError:
    """Coerce a lane failure into an :class:`AgentLaneError`.

    Unwraps the raised step failures (:attr:`ReviewStepFailure.error`)
    and folds any unrecognised exception into a fresh lane error.
    """
    err = getattr(failure, "error", None)
    if isinstance(err, AgentLaneError):
        return err
    if isinstance(err, ReviewStepError):
        return AgentLaneError(
            message=err.message,
            lane=lane,
            userId=err.userId,
            repoId=err.repoId,
            prNumber=err.prNumber,
            headSha=err.headSha,
            retryable=err.retryable,
        )
    return AgentLaneError(message=str(failure), lane=lane)


@DBOS.step(
    retries_allowed=True,
    max_attempts=3,
    should_retry=shouldRetry,
    backoff_rate=2,
)
async def invokeAgentStep(
    *,
    lane: AgentLane,
    sandboxCtx: SandboxCtx,
    llmCtx: LLMCtx,
    repo: RepoSnapshot,
    input: ReviewWorkflowInput,
    limits: ReviewLimits,
) -> tuple[str, dict[str, UsageMetadata]]:
    """Durable step: run one research lane and return ``(text, usage)``.

    Reconnects to the sandbox by id (via the agent service's backend
    build), builds the lane's deep-agent with its own chat model and
    the shared ``get_diff`` tool, and runs it with the shared user
    prompt. Transient failures retry this lane alone; the sandbox is
    never stopped here.

    Raises:
        TransientReviewStepFailure: transient LLM / sandbox failure —
            DBOS retries this lane.
        ReviewStepFailure: agent construction failed, or the lane
            produced no text. Final for the lane.
    """
    model = createLLMModel(llmCtx)
    if isinstance(model, LLMConfigError):
        raise ReviewStepFailure(
            AgentLaneError(
                message=f"failed to build chat model: {model}",
                lane=lane,
                userId=input.userId,
                repoId=repo.id,
                prNumber=input.prNumber,
                headSha=input.headSha,
            )
        )

    agentCtx = createReviewAgentCtx(
        userId=input.userId,
        repoId=repo.id,
        repoName=repo.repoName,
        prNumber=input.prNumber,
        headSha=input.headSha,
        model=model,
        sandboxCtx=sandboxCtx,
        modelCallRunLimit=limits.modelCallRunLimit,
        toolCallRunLimit=limits.toolCallRunLimit,
    )

    agent: DeepAgentGraph | AgentBuildError | SandboxProviderError
    if lane == "summarizer":
        agent = await createSummaryAgent(agentCtx)
    else:
        agent = await createCommentsAgent(agentCtx)

    if isinstance(agent, SandboxProviderError):
        raise TransientReviewStepFailure(
            AgentLaneError(
                message=f"sandbox backend failed for lane={lane}: {agent.message}",
                lane=lane,
                userId=input.userId,
                repoId=repo.id,
                prNumber=input.prNumber,
                headSha=input.headSha,
                retryable=True,
            )
        )
    if isinstance(agent, AgentBuildError):
        raise ReviewStepFailure(
            AgentLaneError(
                message=f"agent build failed for lane={lane}: {agent.message}",
                lane=lane,
                userId=input.userId,
                repoId=repo.id,
                prNumber=input.prNumber,
                headSha=input.headSha,
            )
        )

    prompt = createUserPrompt(agentCtx)
    promptPayload = {"messages": [{"role": "user", "content": prompt}]}

    result: Any = None
    try:
        with get_usage_metadata_callback() as usage_cb:
            result = await agent.ainvoke(promptPayload)
            usage = usage_cb.usage_metadata
    except Exception as exc:
        retryable = isLlmRetryError(exc)
        log.warning(
            "invoke_agent_step: lane=%s failed (retryable=%s): %s: %s",
            lane,
            retryable,
            type(exc).__name__,
            exc,
        )
        if retryable:
            raise TransientReviewStepFailure(
                AgentLaneError(
                    message=f"lane={lane} {type(exc).__name__}: {exc}",
                    lane=lane,
                    userId=input.userId,
                    repoId=repo.id,
                    prNumber=input.prNumber,
                    headSha=input.headSha,
                    retryable=True,
                )
            ) from exc
        raise ReviewStepFailure(
            AgentLaneError(
                message=f"lane={lane} {type(exc).__name__}: {exc}",
                lane=lane,
                userId=input.userId,
                repoId=repo.id,
                prNumber=input.prNumber,
                headSha=input.headSha,
            )
        ) from exc

    text = _lastAiText(result)
    if not text.strip():
        raise ReviewStepFailure(
            AgentLaneError(
                message=f"lane={lane} produced no text output",
                lane=lane,
                userId=input.userId,
                repoId=repo.id,
                prNumber=input.prNumber,
                headSha=input.headSha,
            )
        )

    log.info(
        "invoke_agent_step: ok lane=%s repo=%s user=%s pr_number=%s",
        lane,
        repo.repoName,
        input.userId,
        input.prNumber,
    )
    return text, usage


async def runExtractorLanes(
    agentResults: Sequence[AgentStepOutcome],
    *,
    extractorLlmCtx: LLMCtx,
) -> ExtractorLaneResults:
    """Run the structured-extractor steps for the lanes that succeeded.

    ``agentResults`` holds the two :func:`asyncio.gather` outcomes in
    the deterministic order of :data:`AGENT_LANES`. For every
    successful lane the matching durable extractor step is awaited
    (sequentially); an extractor failure is captured as the lane's
    outcome so the workflow's combine step can degrade the lane.
    Failed agent lanes carry their error through unchanged.
    """
    summaryAgentOutcome = agentResults[0]
    commentsAgentOutcome = agentResults[1]

    summaryLane: SummaryLaneOutcome
    if isinstance(summaryAgentOutcome, BaseException):
        summaryLane = summaryAgentOutcome
    else:
        rawText, agentUsage = summaryAgentOutcome
        try:
            extracted, _extractorUsage = await extractSummaryStep(
                extractorLlmCtx=extractorLlmCtx,
                rawText=rawText,
            )
        except BaseException as exc:
            summaryLane = exc
        else:
            summaryLane = (extracted, agentUsage)

    commentsLane: CommentsLaneOutcome
    if isinstance(commentsAgentOutcome, BaseException):
        commentsLane = commentsAgentOutcome
    else:
        rawText, agentUsage = commentsAgentOutcome
        try:
            extracted, _extractorUsage = await extractCommentsStep(
                extractorLlmCtx=extractorLlmCtx,
                rawText=rawText,
            )
        except BaseException as exc:
            commentsLane = exc
        else:
            commentsLane = (extracted, agentUsage)

    return ExtractorLaneResults(
        summarizer=summaryLane,
        comments=commentsLane,
    )


def combineLaneOutcomes(
    laneOutcomes: ExtractorLaneResults,
    *,
    prNumber: PRNumber,
    headSha: CommitId,
    repoId: RepoId,
    userId: UserId,
) -> CombinedReview | ReviewAgentsError:
    """Partition the lane outcomes and combine them into a review.

    Both lanes failed → :class:`ReviewAgentsError` (each lane already
    exhausted its own step retries, so the workflow marks the run
    ERROR). Partial failure → the failed lane degrades to an empty
    default and the review is built from the successful lane. Token
    usage is aggregated from the successful lanes only.
    """
    failures: list[tuple[AgentLane, AgentLaneError]] = []
    summaryMarkdown: str = _DEFAULT_SUMMARY
    comments: ReviewComments = ReviewComments(List=[])

    totalUsagesPerPr = TotalUsagesPerPR(
        pr_number=prNumber,
        head_sha=headSha,
        repo_id=repoId,
        user_id=userId,
        usages={},
    )

    summarizerValue = laneOutcomes["summarizer"]
    if isinstance(summarizerValue, BaseException):
        failures.append(("summarizer", _laneError(summarizerValue, "summarizer")))
    else:
        summaryResult, summaryUsage = summarizerValue
        summaryMarkdown = summaryResult.summary
        _accumulateUsage(totalUsagesPerPr["usages"], summaryUsage)

    commentsValue = laneOutcomes["comments"]
    if isinstance(commentsValue, BaseException):
        failures.append(("comments", _laneError(commentsValue, "comments")))
    else:
        commentsResult, commentsUsage = commentsValue
        comments = commentsResult
        _accumulateUsage(totalUsagesPerPr["usages"], commentsUsage)

    if len(failures) == len(AGENT_LANES):
        return ReviewAgentsError(
            message=(
                f"review agents invocation failed for pr={prNumber} "
                f"head_sha={headSha[:7]}: failed="
                f"{[lane for lane, _ in failures]}"
            ),
            userId=userId,
            repoId=repoId,
            prNumber=prNumber,
            headSha=headSha,
            failedLanes=[err for _, err in failures],
            succeededLanes=[],
        )

    if failures:
        log.warning(
            "review agents partial failure: failed=%s pr_number=%s head_sha=%s",
            [(lane, err.message) for lane, err in failures],
            prNumber,
            headSha[:7],
        )

    return CombinedReview(
        review=combineReviewResults(
            summaryMarkdown=summaryMarkdown,
            comments=comments,
        ),
        usages=totalUsagesPerPr,
    )


def _accumulateUsage(
    buckets: dict[str, TotalUsages],
    usage: dict[str, UsageMetadata],
) -> None:
    """Accumulate one lane's per-model usage into the run's buckets.

    ``buckets`` is the ``usages`` map of a :class:`TotalUsagesPerPR`
    envelope; each model gets a :class:`TotalUsages` counter with the
    input / output / total token counts and the cache details merged.
    """
    for modelName, perModel in usage.items():
        bucket = buckets.setdefault(
            modelName,
            TotalUsages(
                input_tokens=0,
                output_tokens=0,
                total_tokens=0,
                input_token_details=InputTokenDetails(
                    cache_read=0,
                    cache_creation=0,
                ),
            ),
        )
        bucket["input_tokens"] += perModel.get("input_tokens", 0)
        bucket["output_tokens"] += perModel.get("output_tokens", 0)
        bucket["total_tokens"] += perModel.get("total_tokens", 0)
        details = perModel.get("input_token_details") or {}
        prevCacheRead = bucket["input_token_details"].get("cache_read")
        prevCacheCreation = bucket["input_token_details"].get("cache_creation")
        bucket["input_token_details"]["cache_read"] = (
            prevCacheRead if prevCacheRead is not None else 0
        ) + (details.get("cache_read") or 0)
        bucket["input_token_details"]["cache_creation"] = (
            prevCacheCreation if prevCacheCreation is not None else 0
        ) + (details.get("cache_creation") or 0)


__all__ = [
    "AGENT_LANES",
    "AgentStepOutcome",
    "CombinedReview",
    "ExtractorLaneResults",
    "combineLaneOutcomes",
    "invokeAgentStep",
    "runExtractorLanes",
]