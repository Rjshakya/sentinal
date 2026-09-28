"""DBOS durable steps that run the planning agent.

Two steps, replacing the old research + LLM-extractor split:

1. :func:`invokePlannerStep` — builds the run's chat model from the
   :class:`LLMCtx`, assembles an :class:`AgentV2Ctx`, builds the
   planning agent (:func:`createPlanningAgent`, no subagents, no
   delegation) and runs it with the inventory-grounded user prompt,
   capturing token usage. The agent persists its plan itself via the
   ``submit_plan`` tool (``plan.json`` in the sandbox working dir).
   Returns the usage envelope only.
2. :func:`getPlanStep` — reconnects to the sandbox, reads back the
   submitted ``plan.json``, and validates it into a
   :class:`PlannerContext`. No LLM call: transcription is a file
   read plus Pydantic validation. The I/O and parsing live in the
   pure value-returning workers :func:`readPlanText` and
   :func:`parsePlanText` (mirroring
   :func:`app.workflows.review_v2.steps.list_chunks.listChunkFiles`);
   the DBOS step is a thin edge mapping error values to raised
   step exceptions.

A transient failure (LLM 429 / 5xx / timeout, sandbox blip) raises
:class:`TransientReviewStepFailure` (DBOS retries the step); a final
failure raises :class:`ReviewStepFailure` wrapping a
:class:`PlannerStepError` with the matching ``phase``. The workflow
degrades a final planner failure to an empty :class:`PlannerContext`
(the planner is enrichment-only) — it never fails the run over it.

The invoke step never stops the sandbox — the workflow's ``finally``
(:func:`app.workflows.review_v2.steps.kill_sandbox.killSandboxStep`)
owns the stop.
"""

from __future__ import annotations

import logging
from typing import Literal, Protocol, cast

from dbos import DBOS
from deepagents.backends.protocol import ReadResult
from langchain_core.callbacks import get_usage_metadata_callback
from langchain_core.messages import UsageMetadata
from langgraph.store.base import Result

from app.services.agent_v2.errors import AgentV2BuildError
from app.services.agent_v2.prompts import createPlanningUserPrompt
from app.services.agent_v2.prompts.planning import createPlanningSystemPrompt
from app.services.agent_v2.service import (
    buildNoSubBackend,
    createAgentV2Ctx,
    createPlanningAgent,
    planFilePath,
)
from app.services.agent_v2.types import DeepAgentGraph, PlannerContext
from app.services.llm.errors import LLMConfigError
from app.services.llm.service import createLLMModel
from app.services.llm.types import LLMCtx
from app.services.sandbox.errors import SandboxProviderError
from app.services.sandbox.types import SandboxCtx
from app.utils.branded import RepoId
from app.workflows.review_v2.errors import (
    PlannerStepError,
    ReviewStepFailure,
    TransientReviewStepFailure,
    isLlmRetryError,
    shouldRetry,
)
from app.workflows.review_v2.types import (
    RepoSnapshot,
    ReviewLimits,
    ReviewWorkflowInput,
)

log = logging.getLogger(__name__)

PlannerStepOutcome = dict[str, UsageMetadata] | BaseException
"""Outcome of the planner research step: the usage envelope or a
wrapped :class:`PlannerStepError`. The plan itself travels via the
sandbox (``submit_plan`` tool → ``plan.json``), read back by
:func:`getPlanStep`."""


class _PlanReader(Protocol):
    """The backend surface the plan reader needs (line-paginated read)."""

    async def aread(
        self, file_path: str, offset: int = 0, limit: int = 2000
    ) -> ReadResult: ...


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
) -> dict[str, UsageMetadata]:
    """Durable step: run the planning agent, return the usage envelope.

    Reconnects to the sandbox by id (via the agent-v2 backend build),
    builds the no-delegation planning agent with its own chat model
    (plus the ``submit_plan`` tool alongside the backend's built-in
    read tools), and runs it with the inventory-grounded user prompt.
    The agent persists its own plan via ``submit_plan``; the text it
    ends with is irrelevant — :func:`getPlanStep` reads the plan back.
    The sandbox is never stopped here.

    Raises:
        TransientReviewStepFailure: transient LLM / sandbox failure —
            DBOS retries.
        ReviewStepFailure: agent construction failed. Final for the
            step (the workflow degrades to an empty planner context).
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

    planningAgentSystemPrompt = createPlanningSystemPrompt(
        repoName=repo.repoName,
        userId=input.userId,
        modelCallRunLimit=limits.modelCallRunLimit,
        toolCallRunLimit=limits.toolCallRunLimit,
    )

    agentCtx = createAgentV2Ctx(
        userId=input.userId,
        repoId=repo.id,
        repoName=repo.repoName,
        prNumber=input.prNumber,
        headSha=input.headSha,
        model=model,
        systemPrompt=planningAgentSystemPrompt,
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

    prompt = createPlanningUserPrompt(
        agentCtx,
        actualFiles=actualFiles,
        title=input.title,
        body=input.body,
        author=input.author,
    )
    promptPayload = {"messages": [{"role": "user", "content": prompt}]}

    try:
        with get_usage_metadata_callback() as usage_cb:
            await agent.ainvoke(promptPayload)
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

    log.info(
        "invoke_planner_step: ok repo=%s user=%s pr_number=%s files=%d",
        repo.repoName,
        input.userId,
        input.prNumber,
        len(actualFiles),
    )
    return usage


_PLAN_READ_LIMIT = 3000
"""Page size for the paginated ``aread`` loop in :func:`readPlanText`."""


async def readPlanText(
    backend: _PlanReader,
    *,
    planPath: str,
    input: ReviewWorkflowInput,
    repoId: RepoId,
) -> str | PlannerStepError:
    """Read the submitted ``plan.json`` into its raw JSON text.

    Paginates ``aread`` from ``offset=0`` until an empty page — or the
    backend's past-EOF error (``offset`` beyond the file's line count)
    once at least one page is accumulated. Returns the accumulated
    text, or a :class:`PlannerStepError` value (never raises) so the
    DBOS edge can map ``retryable`` to the raised step exception.
    ``phase`` is always ``"research"``: a missing submission is a
    research outcome, not an extract failure.
    """
    chunks: list[str] = []
    offset = 0

    while True:
        try:
            res: ReadResult = await backend.aread(
                planPath,
                offset=offset,
                limit=_PLAN_READ_LIMIT,
            )
        except Exception as exc:
            return _plannerError(
                message=f"plan read {type(exc).__name__}: {exc}",
                phase="research",
                input=input,
                repoId=repoId,
                retryable=True,
            )

        if res.error is not None:
            if chunks and "exceeds file length" in (res.error or ""):
                # Past-EOF signal after progress: the accumulated text
                # is the complete file. Only a first-page error means
                # the agent never submitted.
                break
            return _plannerError(
                message=(
                    "planner never submitted a plan: " f"{res.error or 'empty read'}"
                ),
                phase="research",
                input=input,
                repoId=repoId,
            )

        content: str = res.file_data["content"] if res.file_data is not None else ""
        if content:
            chunks.append(content)
            offset += _PLAN_READ_LIMIT
        else:
            break

    return "".join(chunks)


def parsePlanText(
    text: str,
    *,
    input: ReviewWorkflowInput,
    repoId: RepoId,
) -> PlannerContext | PlannerStepError:
    """Validate raw ``plan.json`` text into a :class:`PlannerContext`.

    Pure: Pydantic validation only, no I/O. Returns the plan or a
    :class:`PlannerStepError` value with ``phase="extract"`` (business
    outcome — the workflow degrades to an empty planner context).
    """
    try:
        return PlannerContext.model_validate_json(text)
    except Exception as exc:
        return _plannerError(
            message=f"submitted plan invalid: {type(exc).__name__}: {exc}",
            phase="extract",
            input=input,
            repoId=repoId,
        )


@DBOS.step(
    retries_allowed=True,
    max_attempts=3,
    should_retry=shouldRetry,
    backoff_rate=2,
)
async def getPlanStep(
    *,
    sandboxCtx: SandboxCtx,
    repoId: RepoId,
    input: ReviewWorkflowInput,
) -> PlannerContext:
    """Durable step: read the submitted ``plan.json`` into a :class:`PlannerContext`.

    Reconnects to the sandbox by id and reads the plan the agent
    persisted via ``submit_plan`` (same host-owned path, recomputed —
    never trusted from the agent). No LLM call: transcription is a
    file read (:func:`readPlanText`) plus Pydantic validation
    (:func:`parsePlanText`).

    Raises:
        TransientReviewStepFailure: sandbox reconnect / read failed.
            DBOS retries (the submitted file survives — no agent
            re-run needed on read retries).
        ReviewStepFailure: the agent never submitted (missing file)
            or the submission is unparseable. Business outcome — the
            workflow degrades to an empty planner context.
    """
    backend = await buildNoSubBackend(sandboxCtx)
    if isinstance(backend, SandboxProviderError):
        raise TransientReviewStepFailure(
            _plannerError(
                message=f"plan read: sandbox backend failed: {backend.message}",
                phase="research",
                input=input,
                repoId=repoId,
                retryable=True,
            )
        )

    text = await readPlanText(
        cast(_PlanReader, backend),
        planPath=planFilePath(sandboxCtx.rootPath),
        input=input,
        repoId=repoId,
    )
    if isinstance(text, PlannerStepError):
        if text.retryable:
            raise TransientReviewStepFailure(text)
        raise ReviewStepFailure(text)

    plan = parsePlanText(text, input=input, repoId=repoId)
    if isinstance(plan, PlannerStepError):
        raise ReviewStepFailure(plan)

    log.info("get_plan_step: ok files=%d", len(plan.fileContexts))
    return plan


__all__ = [
    "PlannerStepOutcome",
    "getPlanStep",
    "invokePlannerStep",
    "parsePlanText",
    "readPlanText",
]
