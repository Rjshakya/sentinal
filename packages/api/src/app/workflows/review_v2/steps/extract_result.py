"""Structured extractor: turn the file agents' findings report into
validated review comments.

Re-invokes a small structured-output-capable OpenAI model with the
report text and the :class:`ReviewComments` schema bound via
``with_structured_output``: transcribes each finding block into a
:class:`CodeCommentDraft` (exact anchors; anchor-less findings are
dropped) and reformats each body to the comment-body contract.
Transient LLM failures raise :class:`TransientReviewStepFailure`; a
schema mismatch is a business outcome (:class:`ExtractionError`) that
degrades instead of failing the review.
"""

from __future__ import annotations

import json
import logging

from langchain_core.callbacks import get_usage_metadata_callback
from langchain_core.messages import HumanMessage, SystemMessage, UsageMetadata
from langchain_core.runnables import RunnableConfig
from langfuse import observe

from app.core.config import settings
from app.services.agent_v2.prompts.shared import COMMENT_BODY_FORMAT
from app.services.llm.service import createLLMModel
from app.services.llm.types import LLMCtx
from app.services.tracing.service import (
    buildAgentConfig,
    createTraceCallbacks,
    propagateReviewAttrs,
)
from app.services.tracing.types import ReviewTraceCtx
from app.utils.branded import ApiKey
from app.utils.schema import ReviewComments
from app.workflows.review_v2.errors import (
    ExtractionError,
    ReviewStepFailure,
    TransientReviewStepFailure,
    isLlmRetryError,
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
    + json.dumps(ReviewComments.model_json_schema(), indent=2)
)
"""System prompt for the comments extractor (transcription + contract formatting)."""


def extractionError(message: str, *, retryable: bool = False) -> Exception:
    return (TransientReviewStepFailure if retryable else ReviewStepFailure)(
        ExtractionError(message=message, lane="comments", retryable=retryable)
    )


@observe(name="extract-comments", capture_input=False)
async def extractCommentsStep(
    *,
    extractorLlmCtx: LLMCtx,
    rawText: str,
    traceCtx: ReviewTraceCtx | None = None,
) -> tuple[ReviewComments, dict[str, UsageMetadata]]:
    """Transcribe the findings report into :class:`ReviewComments`.

    Raises:
        TransientReviewStepFailure: transient LLM failure.
        ReviewStepFailure: empty input or schema mismatch.
    """
    if not rawText.strip():
        raise extractionError("research agent produced no text output")

    chat = createLLMModel(extractorLlmCtx)
    if isinstance(chat, ValueError):
        raise extractionError(f"failed to build extractor model: {chat}")

    if traceCtx is not None:
        agentConfig: RunnableConfig = buildAgentConfig(
            ctx=traceCtx,
            runName="extract-comments",
            lane="lane:extract",
            extraMetadata={"input_chars": len(rawText)},
        )
    else:
        agentConfig = {"run_name": "extract-comments"}
        callbacks = createTraceCallbacks()
        if callbacks:
            agentConfig["callbacks"] = callbacks

    try:
        structured = chat.with_structured_output(ReviewComments)
        if traceCtx is not None:
            with propagateReviewAttrs(ctx=traceCtx, traceName="review-extract"):
                with get_usage_metadata_callback() as usage_cb:
                    response = await structured.ainvoke(
                        [
                            SystemMessage(content=COMMENTS_EXTRACTION_SYSTEM_PROMPT),
                            HumanMessage(content=rawText),
                        ],
                        config=agentConfig,
                    )
                    usage = usage_cb.usage_metadata
        else:
            with get_usage_metadata_callback() as usage_cb:
                response = await structured.ainvoke(
                    [
                        SystemMessage(content=COMMENTS_EXTRACTION_SYSTEM_PROMPT),
                        HumanMessage(content=rawText),
                    ],
                    config=agentConfig,
                )
                usage = usage_cb.usage_metadata
        result = ReviewComments.model_validate(response)
    except Exception as exc:
        if isinstance(exc, (TransientReviewStepFailure, ReviewStepFailure)):
            raise
        raise extractionError(
            f"extractor {type(exc).__name__}: {exc}",
            retryable=isLlmRetryError(exc),
        ) from exc
    log.info("extracting comments result: input_chars=%d", len(rawText))
    return result, usage


__all__ = [
    "COMMENTS_EXTRACTION_SYSTEM_PROMPT",
    "buildExtractorLlmCtx",
    "extractCommentsStep",
]