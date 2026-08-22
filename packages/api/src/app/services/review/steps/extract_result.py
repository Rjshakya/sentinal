"""DBOS durable steps that turn the research agents' free-form output into
structured review payloads.

The two research agents (:func:`app.services.review.agent.build_summary_agent`
and :func:`app.services.review.agent.build_comments_agent`) are prompt-driven
and end their runs with free-form text — the summarizer writes the markdown
walkthrough directly, the comments agent writes a findings report. Neither
produces a structured payload.

These steps re-invoke a small, structured-output-capable OpenAI model
(:data:`_EXTRACTOR_MODEL`) with the agent's text and the target schema bound
via ``with_structured_output``, so the pipeline always receives validated
:class:`SummaryResult` / :class:`ReviewComments` payloads regardless of how
the research agent ended its run:

- :func:`extract_summary_result_step` — verbatim wrap: the agent's
  walkthrough text becomes the ``summary`` field unchanged.
- :func:`extract_comments_result_step` — transcribes the findings report's
  blocks into :class:`CodeCommentDraft` entries (exact anchors; findings
  without usable anchors are dropped) and reformats each comment body to
  the shared comment-body contract
  (:data:`app.services.agent.prompts.COMMENT_BODY_FORMAT`) — headline →
  grounded issue bullets → ``**Fix:**`` line — without adding or dropping
  substance.

Both are durable :func:`@DBOS.step` steps: transient LLM failures (429 / 5xx
/ timeout, classified by :func:`app.services.review.errors.is_llm_retry_error`)
are retried up to ``max_attempts`` times; a structured-output schema mismatch
is a business outcome (:class:`SummaryExtractionError` /
:class:`CommentsExtractionError`) that the workflow's combine step degrades
instead of failing the whole review.

The extractor model is OpenAI-only (strong structured-output support). Its
config is built by :func:`build_extractor_config` from the existing
``settings.openai_api_key`` — no extra env surface.
"""

from __future__ import annotations

import logging
from typing import cast

from dbos import DBOS
from langchain_core.callbacks import get_usage_metadata_callback
from langchain_core.messages import HumanMessage, SystemMessage, UsageMetadata

from app.core.config import settings
from app.core.llm import LLMConfig, build_chat_model
from app.services.agent.models import ReviewComments, SummaryResult
from app.services.agent.prompts import COMMENT_BODY_FORMAT, _render_schema
from app.services.review._internal import _SHOULD_RETRY_TRANSIENT
from app.services.review.errors import (
    CommentsExtractionError,
    ReviewAgentRateLimitedError,
    SummaryExtractionError,
    extract_retry_after_seconds,
    is_llm_retry_error,
)

log = logging.getLogger(__name__)

_EXTRACTOR_MODEL = "openai:gpt-5.6-luna"
"""The OpenAI model used for structured extraction.

Small, cheap, and reliable at forced-tool structured output — the
research agents are free to end with any text, and this model turns it
into the validated schema payload.
"""


def build_extractor_config() -> LLMConfig:
    """Build the :class:`LLMConfig` for the structured-output extractor.

    OpenAI-only, keyed from the existing ``settings.openai_api_key``
    (falls back to the provider's native ``OPENAI_API_KEY`` env when
    blank). No new env surface.
    """
    return LLMConfig(
        model=_EXTRACTOR_MODEL,
        api_key=settings.openai_api_key or None,
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


# --------------------------------------------------------------------------- #
# Shared extraction helper                                                      #
# --------------------------------------------------------------------------- #

_ExtractableModel = type[SummaryResult] | type[ReviewComments]
_ExtractionError = type[SummaryExtractionError] | type[CommentsExtractionError]


async def _extract_structured(
    *,
    extractor_config: LLMConfig,
    source_text: str,
    model_cls: _ExtractableModel,
    system_prompt: str,
) -> tuple[SummaryResult | ReviewComments, dict[str, UsageMetadata]]:
    """Run one structured-output call against ``source_text``.

    Binds ``model_cls`` via ``with_structured_output`` (forced tool
    choice) and validates the returned payload. Token usage is captured
    with :func:`get_usage_metadata_callback` so the extractor's tokens
    land in the per-PR ``review_usages`` envelope.
    """
    chat = build_chat_model(config=extractor_config)
    structured = chat.with_structured_output(model_cls)

    with get_usage_metadata_callback() as usage_cb:
        response = await structured.ainvoke(
            [
                SystemMessage(content=system_prompt),
                HumanMessage(content=source_text),
            ]
        )
        usage = usage_cb.usage_metadata

    return model_cls.model_validate(response), usage


async def _run_extractor(
    *,
    extractor_config: LLMConfig,
    source_text: str,
    model_cls: _ExtractableModel,
    system_prompt: str,
    error_cls: _ExtractionError,
    lane: str,
) -> tuple[SummaryResult | ReviewComments, dict[str, UsageMetadata]]:
    """Run :func:`_extract_structured` with the lane's error semantics.

    Transient LLM failures (429 / 5xx / timeout) are re-raised as
    :class:`ReviewAgentRateLimitedError` so the step's
    ``should_retry=_SHOULD_RETRY_TRANSIENT`` retries them; anything else
    (empty input, schema mismatch, provider 4xx) becomes the lane's
    non-transient extraction error.
    """
    if not source_text.strip():
        raise error_cls(cause="research agent produced no text output")

    try:
        return await _extract_structured(
            extractor_config=extractor_config,
            source_text=source_text,
            model_cls=model_cls,
            system_prompt=system_prompt,
        )
    except Exception as exc:
        if is_llm_retry_error(exc):
            retry_after = extract_retry_after_seconds(exc)
            raise ReviewAgentRateLimitedError(
                cause=f"extractor lane={lane} {type(exc).__name__}: {exc}",
                retry_after_seconds=retry_after,
            ) from exc
        raise error_cls(cause=f"{type(exc).__name__}: {exc}") from exc


# --------------------------------------------------------------------------- #
# Durable extractor steps                                                       #
# --------------------------------------------------------------------------- #


@DBOS.step(
    retries_allowed=True,
    max_attempts=3,
    should_retry=_SHOULD_RETRY_TRANSIENT,
)
async def extract_summary_result_step(
    *,
    extractor_config: LLMConfig,
    raw_text: str,
) -> tuple[SummaryResult, dict[str, UsageMetadata]]:
    """Durable step: wrap the summarizer's walkthrough into a
    :class:`SummaryResult` (verbatim).

    ``raw_text`` is the summarizer agent's final message. The extractor
    re-invokes :data:`_EXTRACTOR_MODEL` with the schema bound and places
    the text verbatim into the ``summary`` field.

    Raises:
        ReviewAgentRateLimitedError: transient LLM failure —
            :class:`TransientStepError`, retried by DBOS.
        SummaryExtractionError: extraction failed or returned a payload
            that does not validate. Business outcome — not retried.
    """
    log.info("extracting summary result: input_chars=%d", len(raw_text))
    result, usage = await _run_extractor(
        extractor_config=extractor_config,
        source_text=raw_text,
        model_cls=SummaryResult,
        system_prompt=SUMMARY_EXTRACTION_SYSTEM_PROMPT,
        error_cls=SummaryExtractionError,
        lane="summarizer",
    )
    return cast(SummaryResult, result), usage


@DBOS.step(
    retries_allowed=True,
    max_attempts=3,
    should_retry=_SHOULD_RETRY_TRANSIENT,
)
async def extract_comments_result_step(
    *,
    extractor_config: LLMConfig,
    raw_text: str,
) -> tuple[ReviewComments, dict[str, UsageMetadata]]:
    """Durable step: transcribe the comments agent's findings report into
    a :class:`ReviewComments`.

    ``raw_text`` is the comments agent's final message (the findings
    report). The extractor re-invokes :data:`_EXTRACTOR_MODEL` with the
    schema bound and transcribes each finding block into a
    :class:`CodeCommentDraft`, reformatting the comment body to the
    shared comment-body contract; findings without usable anchors are
    dropped, and an empty / ``NO_FINDINGS`` report yields an empty list.

    Raises:
        ReviewAgentRateLimitedError: transient LLM failure —
            :class:`TransientStepError`, retried by DBOS.
        CommentsExtractionError: extraction failed or returned a payload
            that does not validate. Business outcome — not retried.
    """
    log.info("extracting comments result: input_chars=%d", len(raw_text))
    result, usage = await _run_extractor(
        extractor_config=extractor_config,
        source_text=raw_text,
        model_cls=ReviewComments,
        system_prompt=COMMENTS_EXTRACTION_SYSTEM_PROMPT,
        error_cls=CommentsExtractionError,
        lane="comments",
    )
    return cast(ReviewComments, result), usage


__all__ = [
    "COMMENTS_EXTRACTION_SYSTEM_PROMPT",
    "SUMMARY_EXTRACTION_SYSTEM_PROMPT",
    "build_extractor_config",
    "extract_comments_result_step",
    "extract_summary_result_step",
]
