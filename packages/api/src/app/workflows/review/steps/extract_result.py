"""Structured-extractor steps: turn the research agents' free-form
output into validated review payloads.

The two research agents (:func:`app.services.agent.service.createSummaryAgent`
and :func:`app.services.agent.service.createCommentsAgent`) end their
runs with free-form text — the summarizer writes the markdown walkthrough
directly, the comments agent writes a findings report. Neither produces
a structured payload.

These steps re-invoke a small structured-output-capable OpenAI model
(:data:`_EXTRACTOR_MODEL`) with the agent's text and the target schema
bound via ``with_structured_output``:

- :func:`extractSummaryStep` — verbatim wrap: the walkthrough text
  becomes the ``summary`` field unchanged.
- :func:`extractCommentsStep` — transcribes the findings report's
  blocks into :class:`CodeCommentDraft` entries (exact anchors;
  findings without usable anchors are dropped) and reformats each
  comment body to the shared comment-body contract.

Both are durable steps: transient LLM failures (classified by
:func:`app.workflows.review.errors.isLlmRetryError`) raise
:class:`TransientReviewStepFailure`; a schema mismatch is a business
outcome (:class:`ExtractionError` with ``retryable=False``) that the
workflow's combine step degrades instead of failing the whole review.
"""

from __future__ import annotations

import logging
from typing import cast

from dbos import DBOS
from langchain_core.callbacks import get_usage_metadata_callback
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage, UsageMetadata

from app.core.config import settings
from app.services.agent.prompts import COMMENT_BODY_FORMAT, _render_schema
from app.services.llm.service import createLLMModel
from app.services.llm.types import LLMCtx
from app.utils.branded import ApiKey
from app.utils.schema import ReviewComments, SummaryResult
from app.workflows.review.errors import (
    AgentLane,
    ExtractionError,
    ReviewStepFailure,
    TransientReviewStepFailure,
    extractRetryAfterSeconds,
    isLlmRetryError,
    shouldRetry,
)

log = logging.getLogger(__name__)

_EXTRACTOR_MODEL = "openai:gpt-5.6-luna"
"""The OpenAI model used for structured extraction.

Small, cheap, and reliable at forced-tool structured output — the
research agents are free to end with any text, and this model turns it
into the validated schema payload.
"""


def buildExtractorLlmCtx() -> LLMCtx:
    """Build the :class:`LLMCtx` for the structured-output extractor.

    OpenAI-only, keyed from the existing ``settings.openai_api_key``
    (falls back to the provider's native ``OPENAI_API_KEY`` env when
    blank). No new env surface.
    """
    return LLMCtx(
        model=_EXTRACTOR_MODEL,
        apiKey=ApiKey(settings.openai_api_key) if settings.openai_api_key else None,
    )


SUMMARY_EXTRACTION_SYSTEM_PROMPT: str = (
    "You are a strict JSON formatter for a PR-review pipeline.\n\n"
    "The user message is a PR review summary written by a research agent. "
    'Put that text VERBATIM into the "summary" field: do not rewrite, '
    "paraphrase, truncate, summarise, or add anything. Preserve all "
    "markdown exactly as written.\n\n"
    "OUTPUT SCHEMA — respond with exactly one JSON object of this shape:\n"
    + _render_schema(SummaryResult)
)
"""System prompt for the summary extractor (verbatim wrap)."""

COMMENTS_EXTRACTION_SYSTEM_PROMPT: str = (
    "You are the scribe for a PR-review pipeline. The user message is a "
    "findings report written by a research agent: one block per finding "
    "with file / side / from_line / to_line / severity / node_type / "
    "comment fields.\n\n"
    "Convert it into CodeCommentDraft entries:\n"
    "- Transcribe file_name, side, from_line, to_line, node_type and "
    "severity EXACTLY as written in the report.\n"
    "- The comment field is the finding's comment body, reformatted to "
    "the comment-body contract below: preserve every fact, claim, and "
    "line/symbol reference, but restructure the text into the contract's "
    "headline / issue-bullets / fix shape. Never add findings, claims, "
    "or line numbers the report does not contain; never drop substance "
    "(only filler such as 'I noticed' or 'please consider' may be "
    "removed).\n"
    "- Never invent anchors: if a finding block lacks usable file / side / "
    "line values, drop that finding.\n"
    "- If the report is empty or contains only NO_FINDINGS, return an "
    "empty List.\n"
    "- Return the entries ordered by severity, P1 first.\n\n"
    + COMMENT_BODY_FORMAT
    + "\n\nOUTPUT SCHEMA — respond with exactly one JSON object of this shape:\n"
    + _render_schema(ReviewComments)
)
"""System prompt for the comments extractor (transcription + contract formatting)."""


async def _extractStructured(
    chat: BaseChatModel,
    *,
    sourceText: str,
    model_cls: type[SummaryResult] | type[ReviewComments],
    systemPrompt: str,
) -> tuple[SummaryResult | ReviewComments, dict[str, UsageMetadata]]:
    """Run one structured-output call against ``sourceText``.

    Binds ``model_cls`` via ``with_structured_output`` (forced tool
    choice) and validates the returned payload. Token usage is captured
    so the extractor's tokens land in the per-PR usage envelope.
    """
    structured = chat.with_structured_output(model_cls)

    with get_usage_metadata_callback() as usage_cb:
        response = await structured.ainvoke(
            [
                SystemMessage(content=systemPrompt),
                HumanMessage(content=sourceText),
            ]
        )
        usage = usage_cb.usage_metadata

    return model_cls.model_validate(response), usage


async def _runExtractor(
    *,
    extractorLlmCtx: LLMCtx,
    sourceText: str,
    lane: AgentLane,
    model_cls: type[SummaryResult] | type[ReviewComments],
    systemPrompt: str,
) -> tuple[SummaryResult | ReviewComments, dict[str, UsageMetadata]]:
    """Run :func:`_extractStructured` with the lane's error semantics.

    Raises:
        TransientReviewStepFailure: transient LLM failure (429 / 5xx /
            timeout) — the step's ``should_retry`` retries it.
        ReviewStepFailure: empty input or a schema mismatch — the
            lane's non-transient extraction error.
    """
    if not sourceText.strip():
        raise ReviewStepFailure(
            ExtractionError(
                message=f"research agent produced no text output for lane={lane}",
                lane=lane,
            )
        )

    chat = createLLMModel(extractorLlmCtx)
    if isinstance(chat, ValueError):
        raise ReviewStepFailure(
            ExtractionError(
                message=f"failed to build extractor model: {chat}",
                lane=lane,
            )
        )

    try:
        return await _extractStructured(
            chat,
            sourceText=sourceText,
            model_cls=model_cls,
            systemPrompt=systemPrompt,
        )
    except Exception as exc:
        if isLlmRetryError(exc):
            retryAfter = extractRetryAfterSeconds(exc)
            raise TransientReviewStepFailure(
                ExtractionError(
                    message=f"extractor lane={lane} {type(exc).__name__}: {exc}",
                    lane=lane,
                    retryable=True,
                )
            ) from exc
        raise ReviewStepFailure(
            ExtractionError(
                message=f"extractor lane={lane} {type(exc).__name__}: {exc}",
                lane=lane,
            )
        ) from exc


@DBOS.step(
    retries_allowed=True,
    max_attempts=3,
    should_retry=shouldRetry,
    backoff_rate=2,
)
async def extractSummaryStep(
    *,
    extractorLlmCtx: LLMCtx,
    rawText: str,
) -> tuple[SummaryResult, dict[str, UsageMetadata]]:
    """Durable step: wrap the summarizer's walkthrough into a
    :class:`SummaryResult` (verbatim).

    Raises:
        TransientReviewStepFailure: transient LLM failure — retried.
        ReviewStepFailure: extraction failed or returned a payload that
            does not validate. Business outcome — the lane degrades.
    """
    result, usage = await _runExtractor(
        extractorLlmCtx=extractorLlmCtx,
        sourceText=rawText,
        lane="summarizer",
        model_cls=SummaryResult,
        systemPrompt=SUMMARY_EXTRACTION_SYSTEM_PROMPT,
    )
    log.info("extracting summary result: input_chars=%d", len(rawText))
    return cast(SummaryResult, result), usage


@DBOS.step(
    retries_allowed=True,
    max_attempts=3,
    should_retry=shouldRetry,
    backoff_rate=2,
)
async def extractCommentsStep(
    *,
    extractorLlmCtx: LLMCtx,
    rawText: str,
) -> tuple[ReviewComments, dict[str, UsageMetadata]]:
    """Durable step: transcribe the comments agent's findings report into
    a :class:`ReviewComments`.

    Raises:
        TransientReviewStepFailure: transient LLM failure — retried.
        ReviewStepFailure: extraction failed or returned a payload that
            does not validate. Business outcome — the lane degrades.
    """
    result, usage = await _runExtractor(
        extractorLlmCtx=extractorLlmCtx,
        sourceText=rawText,
        lane="comments",
        model_cls=ReviewComments,
        systemPrompt=COMMENTS_EXTRACTION_SYSTEM_PROMPT,
    )
    log.info("extracting comments result: input_chars=%d", len(rawText))
    return cast(ReviewComments, result), usage


__all__ = [
    "COMMENTS_EXTRACTION_SYSTEM_PROMPT",
    "SUMMARY_EXTRACTION_SYSTEM_PROMPT",
    "buildExtractorLlmCtx",
    "extractCommentsStep",
    "extractSummaryStep",
]