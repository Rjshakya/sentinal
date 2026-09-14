"""DBOS durable steps that run the planning agent.

Two steps, mirroring the v1 research + extractor split:

1. :func:`invokePlannerStep` — builds the run's chat model from the
   :class:`LLMCtx`, assembles an :class:`AgentV2Ctx`, builds the
   planning agent (:func:`createPlanningAgent`, no subagents, no
   delegation) and runs it with the inventory-grounded user prompt,
   capturing token usage. Returns ``(raw_text, usage)``.
2. :func:`extractPlanStep` — re-invokes the shared structured-output
   extractor model with the planner's text and validates it into a
   :class:`PlannerContext`.

A transient failure (LLM 429 / 5xx / timeout, sandbox blip) raises
:class:`TransientReviewStepFailure` (DBOS retries the step); a final
failure raises :class:`ReviewStepFailure` wrapping a
:class:`PlannerStepError` with the matching ``phase``. The workflow
degrades a final planner failure to an empty :class:`PlannerContext`
(the planner is enrichment-only) — it never fails the run over it.

The invoke step never stops the sandbox — the workflow's ``finally``
(:func:`app.workflows.review.steps.kill_sandbox.killSandboxStep`)
owns the stop.
"""

from __future__ import annotations

import logging
from typing import Any, Literal

from dbos import DBOS
from langchain_core.callbacks import get_usage_metadata_callback
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage, UsageMetadata

from app.services.agent_v2.errors import AgentV2BuildError
from app.services.agent_v2.prompts import PLAN_EXTRACTION_SYSTEM_PROMPT
from app.services.agent_v2.service import (
    createAgentV2Ctx,
    createPlanningAgent,
    createPlanningUserPrompt,
)
from app.services.agent_v2.types import DeepAgentGraph, PlannerContext
from app.services.llm.errors import LLMConfigError
from app.services.llm.service import createLLMModel
from app.services.llm.types import LLMCtx
from app.services.sandbox.errors import SandboxProviderError
from app.services.sandbox.types import SandboxCtx
from app.utils.branded import RepoId
from app.workflows.review.errors import (
    ReviewStepFailure,
    TransientReviewStepFailure,
    isLlmRetryError,
    shouldRetry,
)
from app.workflows.review.steps.extract_result import buildExtractorLlmCtx
from app.workflows.review.types import (
    RepoSnapshot,
    ReviewLimits,
    ReviewWorkflowInput,
)
from app.workflows.review_v2.errors import PlannerStepError

log = logging.getLogger(__name__)

PlannerStepOutcome = tuple[str, dict[str, UsageMetadata]] | BaseException
"""Outcome of the planner research step: ``(raw_text, usage)`` or a
wrapped :class:`PlannerStepError`."""


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


def _plannerError(
    *,
    message: str,
    phase: Literal["research", "extract"],
    input: ReviewWorkflowInput,
    repoId: RepoId,
    retryable: bool = False,
) -> PlannerStepError:
    """Build a :class:`PlannerStepError` carrying the run identity."""
    return PlannerStepError(
        message=message,
        phase=phase,
        userId=input.userId,
        repoId=repoId,
        prNumber=input.prNumber,
        headSha=input.headSha,
        retryable=retryable,
    )


@DBOS.step(
    retries_allowed=True,
    max_attempts=3,
    should_retry=shouldRetry,
    backoff_rate=2,
)
async def invokePlannerStep(
    *,
    sandboxCtx: SandboxCtx,
    llmCtx: LLMCtx,
    repo: RepoSnapshot,
    input: ReviewWorkflowInput,
    actualFiles: list[str],
    limits: ReviewLimits,
) -> tuple[str, dict[str, UsageMetadata]]:
    """Durable step: run the planning agent, return ``(text, usage)``.

    Reconnects to the sandbox by id (via the agent-v2 backend build),
    builds the no-delegation planning agent with its own chat model
    and an empty custom-tool list (context comes strictly from
    ``overview.md`` / ``splitted_diffs/`` read through the backend's
    built-in tools), and runs it with the inventory-grounded user
    prompt. The sandbox is never stopped here.

    Raises:
        TransientReviewStepFailure: transient LLM / sandbox failure —
            DBOS retries.
        ReviewStepFailure: agent construction failed, or the planner
            produced no text. Final for the step (the workflow
            degrades to an empty planner context).
    """
    model = createLLMModel(llmCtx)
    if isinstance(model, LLMConfigError):
        raise ReviewStepFailure(
            _plannerError(
                message=f"failed to build chat model: {model}",
                phase="research",
                input=input,
                repoId=repo.id,
            )
        )

    agentCtx = createAgentV2Ctx(
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

    agent: DeepAgentGraph | AgentV2BuildError | SandboxProviderError
    agent = await createPlanningAgent(agentCtx)

    if isinstance(agent, SandboxProviderError):
        raise TransientReviewStepFailure(
            _plannerError(
                message=f"sandbox backend failed for planner: {agent.message}",
                phase="research",
                input=input,
                repoId=repo.id,
                retryable=True,
            )
        )
    if isinstance(agent, AgentV2BuildError):
        raise ReviewStepFailure(
            _plannerError(
                message=f"planner build failed: {agent.message}",
                phase="research",
                input=input,
                repoId=repo.id,
            )
        )

    prompt = createPlanningUserPrompt(agentCtx, actualFiles=actualFiles)
    promptPayload = {"messages": [{"role": "user", "content": prompt}]}

    result: Any = None
    try:
        with get_usage_metadata_callback() as usage_cb:
            result = await agent.ainvoke(promptPayload)
            usage = usage_cb.usage_metadata
    except Exception as exc:
        retryable = isLlmRetryError(exc)
        log.warning(
            "invoke_planner_step: failed (retryable=%s): %s: %s",
            retryable,
            type(exc).__name__,
            exc,
        )
        if retryable:
            raise TransientReviewStepFailure(
                _plannerError(
                    message=f"planner {type(exc).__name__}: {exc}",
                    phase="research",
                    input=input,
                    repoId=repo.id,
                    retryable=True,
                )
            ) from exc
        raise ReviewStepFailure(
            _plannerError(
                message=f"planner {type(exc).__name__}: {exc}",
                phase="research",
                input=input,
                repoId=repo.id,
            )
        ) from exc

    text = _lastAiText(result)
    if not text.strip():
        raise ReviewStepFailure(
            _plannerError(
                message="planner produced no text output",
                phase="research",
                input=input,
                repoId=repo.id,
            )
        )

    log.info(
        "invoke_planner_step: ok repo=%s user=%s pr_number=%s files=%d",
        repo.repoName,
        input.userId,
        input.prNumber,
        len(actualFiles),
    )
    return text, usage


@DBOS.step(
    retries_allowed=True,
    max_attempts=3,
    should_retry=shouldRetry,
    backoff_rate=2,
)
async def extractPlanStep(
    *,
    extractorLlmCtx: LLMCtx,
    rawText: str,
    input: ReviewWorkflowInput,
    repoId: RepoId,
) -> tuple[PlannerContext, dict[str, UsageMetadata]]:
    """Durable step: transcribe the planner text into a :class:`PlannerContext`.

    Binds :class:`PlannerContext` via ``with_structured_output``
    (forced tool choice) on the shared extractor model and validates
    the returned payload.

    Raises:
        TransientReviewStepFailure: transient LLM failure — retried.
        ReviewStepFailure: empty input or a schema mismatch. Business
            outcome — the workflow degrades to an empty planner
            context.
    """
    if not rawText.strip():
        raise ReviewStepFailure(
            _plannerError(
                message="planner produced no text output",
                phase="extract",
                input=input,
                repoId=repoId,
            )
        )

    chat: BaseChatModel | LLMConfigError = createLLMModel(extractorLlmCtx)
    if isinstance(chat, LLMConfigError):
        raise ReviewStepFailure(
            _plannerError(
                message=f"failed to build extractor model: {chat}",
                phase="extract",
                input=input,
                repoId=repoId,
            )
        )

    structured = chat.with_structured_output(PlannerContext)
    try:
        with get_usage_metadata_callback() as usage_cb:
            response = await structured.ainvoke(
                [
                    SystemMessage(content=PLAN_EXTRACTION_SYSTEM_PROMPT),
                    HumanMessage(content=rawText),
                ]
            )
            usage = usage_cb.usage_metadata
    except Exception as exc:
        if isLlmRetryError(exc):
            raise TransientReviewStepFailure(
                _plannerError(
                    message=f"plan extractor {type(exc).__name__}: {exc}",
                    phase="extract",
                    input=input,
                    repoId=repoId,
                    retryable=True,
                )
            ) from exc
        raise ReviewStepFailure(
            _plannerError(
                message=f"plan extractor {type(exc).__name__}: {exc}",
                phase="extract",
                input=input,
                repoId=repoId,
            )
        ) from exc

    log.info("extract_plan_step: ok input_chars=%d", len(rawText))
    return PlannerContext.model_validate(response), usage


def buildPlanExtractorLlmCtx() -> LLMCtx:
    """Return the shared structured-output extractor ctx.

    The plan extractor uses the same small model as the v1 comment /
    summary extractors — re-exported here under a v2 name so the v2
    workflow never reaches into v1 step internals.
    """
    return buildExtractorLlmCtx()


__all__ = [
    "PlannerStepOutcome",
    "buildPlanExtractorLlmCtx",
    "extractPlanStep",
    "invokePlannerStep",
]
