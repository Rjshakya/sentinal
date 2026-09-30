"""Walkthrough-summary worker.

:func:`synthesizeSummaryStep` turns already-validated run data — the
PR metadata, the host-side chunk inventory, the :class:`PlannerContext`
(enrichment), and the extracted :class:`ReviewComments` — into the
walkthrough via one cheap structured-output LLM call
(:class:`SummaryResult`).

No sandbox access, no diff reads: every claim the synthesizer may
emit must already be present in its user message. A transient LLM
failure (429 / 5xx / timeout) raises
:class:`TransientReviewStepFailure`; a final failure (model-build
error, schema mismatch) raises :class:`ReviewStepFailure` wrapping a
:class:`SummaryStepError` — the pipeline degrades to an empty summary
instead of failing the run.
"""

from __future__ import annotations

import logging

from langchain_core.callbacks import get_usage_metadata_callback
from langchain_core.messages import HumanMessage, SystemMessage, UsageMetadata

from app.services.agent_v2.prompts.summary import (
    createSummarySystemPrompt,
    createSummaryUserPrompt,
)
from app.services.agent_v2.types import ChunkInventory, PlannerContext
from app.services.llm.errors import LLMConfigError
from app.services.llm.service import createLLMModel
from app.utils.branded import RepoId
from app.utils.schema import ReviewComments, SummaryResult
from app.workflows.review_v2.errors import (
    ReviewStepFailure,
    SummaryStepError,
    TransientReviewStepFailure,
    isLlmRetryError,
)
from app.workflows.review_v2.steps.extract_result import buildExtractorLlmCtx
from app.workflows.review_v2.types import RepoSnapshot, ReviewWorkflowInput

log = logging.getLogger(__name__)


def summaryError(
    *,
    message: str,
    input: ReviewWorkflowInput,
    repoId: RepoId,
    retryable: bool = False,
) -> SummaryStepError:
    """Build a :class:`SummaryStepError` carrying the run identity."""
    return SummaryStepError(
        message=message,
        userId=input.userId,
        repoId=repoId,
        prNumber=input.prNumber,
        headSha=input.headSha,
        retryable=retryable,
    )


async def synthesizeSummaryStep(
    *,
    input: ReviewWorkflowInput,
    repo: RepoSnapshot,
    inventory: ChunkInventory,
    plannerContext: PlannerContext,
    comments: ReviewComments,
) -> tuple[SummaryResult, dict[str, UsageMetadata]]:
    """Durable step: synthesize the walkthrough summary, return ``(payload, usage)``.

    Builds the extractor-class chat model (shared cheap model, no new
    env), renders the static system contract plus the run-specific
    user message from validated structures, and binds
    :class:`SummaryResult` via ``with_structured_output``.

    Raises:
        TransientReviewStepFailure: transient LLM failure — the SDK retries the step.
        ReviewStepFailure: model-build failure or schema mismatch —
            business outcome, the workflow degrades to an empty summary.
    """
    chat = createLLMModel(buildExtractorLlmCtx())
    if isinstance(chat, LLMConfigError):
        raise ReviewStepFailure(
            summaryError(
                message=f"failed to build summary model: {chat}",
                input=input,
                repoId=repo.id,
            )
        )

    systemPrompt = createSummarySystemPrompt()
    userPrompt = createSummaryUserPrompt(
        repoName=repo.repoName,
        userId=input.userId,
        prNumber=input.prNumber,
        headSha=input.headSha,
        title=input.title,
        body=input.body,
        author=input.author,
        actualFiles=inventory.actualFiles,
        skippedFiles=inventory.skippedFiles,
        plannerContext=plannerContext,
        comments=comments,
    )

    structured = chat.with_structured_output(SummaryResult)
    try:
        with get_usage_metadata_callback() as usage_cb:
            response = await structured.ainvoke(
                [
                    SystemMessage(content=systemPrompt),
                    HumanMessage(content=userPrompt),
                ]
            )
            usage = usage_cb.usage_metadata
    except Exception as exc:
        retryable = isLlmRetryError(exc)
        log.warning(
            "synthesize_summary_step: failed (retryable=%s): %s: %s",
            retryable,
            type(exc).__name__,
            exc,
        )
        if retryable:
            raise TransientReviewStepFailure(
                summaryError(
                    message=f"summary {type(exc).__name__}: {exc}",
                    input=input,
                    repoId=repo.id,
                    retryable=True,
                )
            ) from exc
        raise ReviewStepFailure(
            summaryError(
                message=f"summary {type(exc).__name__}: {exc}",
                input=input,
                repoId=repo.id,
            )
        ) from exc

    try:
        result = SummaryResult.model_validate(response)
    except Exception as exc:
        raise ReviewStepFailure(
            summaryError(
                message=f"summary schema mismatch {type(exc).__name__}: {exc}",
                input=input,
                repoId=repo.id,
            )
        ) from exc

    log.info(
        "synthesize_summary_step: ok pr_number=%s chars=%d",
        input.prNumber,
        len(result.summary),
    )
    return result, usage


__all__ = ["summaryError", "synthesizeSummaryStep"]
