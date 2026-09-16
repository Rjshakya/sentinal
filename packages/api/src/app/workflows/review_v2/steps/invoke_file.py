"""DBOS durable step that runs one per-file review agent.

:func:`invokeFileReviewStep` is parameterized by the file under
review: it builds the run's chat model from the :class:`LLMCtx`,
assembles an :class:`AgentV2Ctx`, builds the file agent
(:func:`createFileReviewAgent`, no subagents, no delegation) and runs
it with the scope-pinned user prompt (its chunk + its planner-context
slice + the shared concerns), capturing token usage. Returns
``(raw_text, usage)``.

A transient failure (LLM 429 / 5xx / timeout, sandbox blip) raises
:class:`TransientReviewStepFailure` (DBOS retries **that file
alone**); a final failure raises :class:`ReviewStepFailure` wrapping
a :class:`FileLaneError`. With ``return_exceptions=True`` the raised
exceptions land in the batch-gather results, so
:func:`app.workflows.review_v2.steps.combine.combineFileOutcomes` can
degrade failed files to nothing.

A ``NO_FINDINGS`` text is a success (the combine step skips it
before extraction). The step never stops the sandbox — the
workflow's ``finally`` owns the stop.
"""

from __future__ import annotations

import logging
from typing import Any

from dbos import DBOS
from langchain_core.callbacks import get_usage_metadata_callback
from langchain_core.messages import UsageMetadata

from app.services.agent_v2.errors import AgentV2BuildError
from app.services.agent_v2.prompts import createFileReviewUserPrompt
from app.services.agent_v2.prompts.file_review import createFileReviewSystemPrompt
from app.services.agent_v2.service import (
    createAgentV2Ctx,
    createFileReviewAgent,
)
from app.services.agent_v2.types import DeepAgentGraph, FileReviewJob
from app.services.llm.errors import LLMConfigError
from app.services.llm.service import createLLMModel
from app.services.llm.types import LLMCtx
from app.services.sandbox.errors import SandboxProviderError
from app.services.sandbox.types import SandboxCtx
from app.workflows.review.errors import (
    ReviewStepFailure,
    TransientReviewStepFailure,
    isLlmRetryError,
    shouldRetry,
)
from app.workflows.review.types import (
    RepoSnapshot,
    ReviewLimits,
    ReviewWorkflowInput,
)
from app.workflows.review_v2.errors import FileLaneError

log = logging.getLogger(__name__)

FileStepOutcome = tuple[str, dict[str, UsageMetadata]] | BaseException
"""Outcome of one per-file review step: ``(raw_text, usage)`` or a
wrapped :class:`FileLaneError`."""


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


@DBOS.step(
    retries_allowed=True,
    max_attempts=3,
    should_retry=shouldRetry,
    backoff_rate=2,
)
async def invokeFileReviewStep(
    *,
    filePath: str,
    job: FileReviewJob,
    sharedConcerns: str,
    sandboxCtx: SandboxCtx,
    llmCtx: LLMCtx,
    repo: RepoSnapshot,
    input: ReviewWorkflowInput,
    limits: ReviewLimits,
) -> tuple[str, dict[str, UsageMetadata]]:
    """Durable step: review one file's chunk, return ``(text, usage)``.

    Raises:
        TransientReviewStepFailure: transient LLM / sandbox failure —
            DBOS retries this file.
        ReviewStepFailure: agent construction failed, or the agent
            produced no text. Final for the file.
    """
    model = createLLMModel(llmCtx)
    if isinstance(model, LLMConfigError):
        raise ReviewStepFailure(
            FileLaneError(
                message=f"failed to build chat model: {model}",
                file=filePath,
                userId=input.userId,
                repoId=repo.id,
                prNumber=input.prNumber,
                headSha=input.headSha,
            )
        )

    fileReviewAgentSystemPrompt = createFileReviewSystemPrompt(
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
        sandboxCtx=sandboxCtx,
        systemPrompt=fileReviewAgentSystemPrompt,
        modelCallRunLimit=limits.modelCallRunLimit,
        toolCallRunLimit=limits.toolCallRunLimit,
    )

    agent: DeepAgentGraph | AgentV2BuildError | SandboxProviderError
    agent = await createFileReviewAgent(agentCtx, filePath=filePath)

    if isinstance(agent, SandboxProviderError):
        raise TransientReviewStepFailure(
            FileLaneError(
                message=f"sandbox backend failed for file={filePath}: {agent.message}",
                file=filePath,
                userId=input.userId,
                repoId=repo.id,
                prNumber=input.prNumber,
                headSha=input.headSha,
                retryable=True,
            )
        )
    if isinstance(agent, AgentV2BuildError):
        raise ReviewStepFailure(
            FileLaneError(
                message=f"file agent build failed for file={filePath}: {agent.message}",
                file=filePath,
                userId=input.userId,
                repoId=repo.id,
                prNumber=input.prNumber,
                headSha=input.headSha,
            )
        )

    prompt = createFileReviewUserPrompt(
        agentCtx,
        job=job,
        sharedConcerns=sharedConcerns,
        title=input.title,
        body=input.body,
        author=input.author,
    )
    promptPayload = {"messages": [{"role": "user", "content": prompt}]}

    result: Any = None
    try:
        with get_usage_metadata_callback() as usage_cb:
            result = await agent.ainvoke(promptPayload)
            usage = usage_cb.usage_metadata
    except Exception as exc:
        retryable = isLlmRetryError(exc)
        log.warning(
            "invoke_file_step: file=%s failed (retryable=%s): %s: %s",
            filePath,
            retryable,
            type(exc).__name__,
            exc,
        )
        if retryable:
            raise TransientReviewStepFailure(
                FileLaneError(
                    message=f"file={filePath} {type(exc).__name__}: {exc}",
                    file=filePath,
                    userId=input.userId,
                    repoId=repo.id,
                    prNumber=input.prNumber,
                    headSha=input.headSha,
                    retryable=True,
                )
            ) from exc
        raise ReviewStepFailure(
            FileLaneError(
                message=f"file={filePath} {type(exc).__name__}: {exc}",
                file=filePath,
                userId=input.userId,
                repoId=repo.id,
                prNumber=input.prNumber,
                headSha=input.headSha,
            )
        ) from exc

    text = _lastAiText(result)
    if not text.strip():
        raise ReviewStepFailure(
            FileLaneError(
                message=f"file={filePath} produced no text output",
                file=filePath,
                userId=input.userId,
                repoId=repo.id,
                prNumber=input.prNumber,
                headSha=input.headSha,
            )
        )

    log.info(
        "invoke_file_step: ok file=%s repo=%s user=%s pr_number=%s",
        filePath,
        repo.repoName,
        input.userId,
        input.prNumber,
    )
    return text, usage


__all__ = ["FileStepOutcome", "invokeFileReviewStep"]
