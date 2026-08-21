"""DBOS durable steps that actually run the review agents.

This module owns the two per-agent steps, the extractor-lane runner
that follows them, and the pure helper that combines their outcomes.

Two parallel research steps:

- :func:`invoke_summary_agent_step` — summarizer (free-form markdown).
- :func:`invoke_comments_agent_step` — comments (free-form findings
  report).

Each step reconnects to the shared E2B sandbox by id, builds its
own chat model and deep-agent (with the shared ``get_diff`` tool),
runs it via the :func:`invoke_<name>_agent` wrappers (which
translate any failure into the per-agent error class with a
``retryable`` flag), and returns ``(raw_text, usage)``. Steps are
started concurrently from the workflow body with
``asyncio.gather(..., return_exceptions=True)`` — the documented
DBOS parallel-steps pattern — and a transient failure (429 / 5xx /
timeout) retries **that lane alone** (``max_attempts=3``,
``backoff_rate=2``) instead of re-running both agents.

The agents are research-only: they produce free-form text, never a
structured payload. :func:`run_extractor_lanes` then dispatches the
durable structured-extractor steps
(:mod:`app.services.review.steps.extract_result`) for the lanes whose
research agent succeeded; failed agent lanes carry their error through.

:func:`combine_agent_outcomes` then partitions the lane outcomes:

- both lanes failed (research **or** extraction) → raises
  :class:`app.services.review.errors.ReviewAgentsInvocationError`
  (pushed to Sentry with the full run context before raising);
- partial failure → failed lane degrades to an empty default (``""``
  summary / ``ReviewComments(List=[])``) with a warning log and the
  review completes with the successful lane's output.

The invoke steps never stop the sandbox: two concurrent steps share
one sandbox, so only the workflow's ``finally``
:func:`app.services.review.steps.stop_sandbox.stop_sandbox_step`
stops it.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any, Literal, TypedDict, cast

import sentry_sdk
from dbos import DBOS
from langchain_core.callbacks import get_usage_metadata_callback
from langchain_core.messages import UsageMetadata
from langchain_e2b import AsyncE2BSandbox

from app.core.llm import LLMConfig, build_chat_model
from app.core.sandbox.e2b import E2BSandbox
from app.services.agent.models import (
    ReviewComments,
    ReviewResult,
    SummaryResult,
)
from app.services.review._internal import _SHOULD_RETRY_AGENT, _e2b_spec
from app.services.review.agent import (
    assemble_user_prompt,
    build_comments_agent,
    build_summary_agent,
    combine_review_results,
)
from app.services.review.errors import (
    CommentsAgentInvocationError,
    ReviewAgentsInvocationError,
    SandboxConnectError,
    StepError,
    SubagentInvocationError,
    SummaryAgentInvocationError,
    is_llm_retry_error,
)
from app.services.review.middleware import build_review_middleware
from app.services.review.steps.extract_result import (
    extract_comments_result_step,
    extract_summary_result_step,
)
from app.services.review.tools import make_get_diff_tool
from app.services.review.types import DeepAgentGraph
from app.services.review.workflow_types import (
    InputTokenDetails,
    TotalUsages,
    TotalUsagesPerPR,
)

log = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Per-subagent wrappers                                                         #
# --------------------------------------------------------------------------- #


def _last_ai_text(result: Any) -> str:
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


async def _call_with_error_wrapping(
    *,
    agent: DeepAgentGraph,
    prompt_payload: dict[str, Any],
    error_cls: type[SubagentInvocationError],
) -> tuple[str, dict[str, UsageMetadata]]:
    """Run ``agent.ainvoke`` and translate any failure into ``error_cls``.

    The wrapper performs two things:

    1. Calls the agent's ``ainvoke`` and returns the last AI message's
       text content — the free-form research output (markdown
       walkthrough for the summarizer, findings report for the
       comments agent). The structured payload is produced afterwards
       by the extractor steps in
       :mod:`app.services.review.steps.extract_result`.
    2. Catches any exception (LLM 5xx/429/timeout from
       :func:`is_llm_retry_error`, empty-output validation errors,
       post-processing errors) and re-raises it as an instance of
       ``error_cls`` with a ``retryable`` flag and any recoverable
       details (message kinds from the partial result). The original
       exception is preserved via ``raise ... from exc`` so Sentry's
       exception chain and Python's ``__cause__`` both work.
    """
    result: Any = None
    try:
        with get_usage_metadata_callback() as usage_cb:
            result = await agent.ainvoke(prompt_payload)
            usage = usage_cb.usage_metadata

        text = _last_ai_text(result)
        if not text.strip():
            raise ValueError("agent produced no text output")
        return text, usage

    except Exception as exc:
        retryable = is_llm_retry_error(exc)
        details: dict[str, Any] = {}
        if isinstance(result, dict):
            from app.services.agent.helpers import extract_message_kinds

            kinds = extract_message_kinds(result.get("messages"))
            if kinds:
                details["message_kinds"] = list(kinds)
        raise error_cls(
            cause=exc,
            retryable=retryable,
            details=details or None,
        ) from exc


async def invoke_summary_agent(
    agent: DeepAgentGraph, prompt_payload: dict[str, Any]
) -> tuple[str, dict[str, UsageMetadata]]:
    """Run the summarizer subagent; on failure raise
    :class:`SummaryAgentInvocationError`. Returns the free-form
    walkthrough text."""
    return await _call_with_error_wrapping(
        agent=agent,
        prompt_payload=prompt_payload,
        error_cls=SummaryAgentInvocationError,
    )


async def invoke_comments_agent(
    agent: DeepAgentGraph, prompt_payload: dict[str, Any]
) -> tuple[str, dict[str, UsageMetadata]]:
    """Run the comments subagent; on failure raise
    :class:`CommentsAgentInvocationError`. Returns the free-form
    findings report text."""
    return await _call_with_error_wrapping(
        agent=agent,
        prompt_payload=prompt_payload,
        error_cls=CommentsAgentInvocationError,
    )


# --------------------------------------------------------------------------- #
# Shared step helpers                                                           #
# --------------------------------------------------------------------------- #


async def _connect_sandbox(
    *,
    sandbox_id: str,
    sandbox_name: str,
    repo_id: str,
    user_id: str,
) -> E2BSandbox:
    """Reconnect to the E2B sandbox by id; wrap failures as
    :class:`SandboxConnectError` so the step's ``should_retry`` retries."""
    spec = _e2b_spec()
    try:
        return await E2BSandbox.connect(
            sandbox_id=sandbox_id,
            sandbox_name=sandbox_name,
            repo_id=repo_id,
            user_id=user_id,
            spec=spec,
            timeout=60 * 60,
            api_key=spec.api_key,
        )
    except Exception as exc:
        raise SandboxConnectError(
            user_id=user_id,
            repo_id=repo_id,
            sandbox_id=sandbox_id,
            cause=f"failed to reconnect sandbox for agents: {type(exc).__name__}: {exc}",
        ) from exc


def _build_prompt_payload(
    *,
    repo_name: str,
    repo_id: str,
    user_id: str,
    pr_number: int,
    head_sha: str,
) -> dict[str, Any]:
    """Build the user message payload sent to every review agent."""
    user_prompt = assemble_user_prompt(
        repo_name=repo_name,
        repo_id=repo_id,
        user_id=user_id,
        pr_number=pr_number,
        head_sha=head_sha,
    )
    return {"messages": [{"role": "user", "content": user_prompt}]}


# --------------------------------------------------------------------------- #
# Per-lane agent steps (run in parallel from the workflow body)                #
# --------------------------------------------------------------------------- #


@DBOS.step(
    retries_allowed=True,
    max_attempts=3,
    should_retry=_SHOULD_RETRY_AGENT,
    backoff_rate=2,
)
async def invoke_summary_agent_step(
    *,
    sandbox_id: str,
    sandbox_name: str,
    repo_id: str,
    repo_name: str,
    user_id: str,
    pr_number: int,
    head_sha: str,
    llm_config: LLMConfig,
    model_call_limit: int,
    tool_call_limit: int,
) -> tuple[str, dict[str, UsageMetadata]]:
    """Durable step: run the summarizer lane and return ``(markdown, usage)``.

    Reconnects to the E2B sandbox by id, builds the summarizer
    deep-agent (own chat model + ``get_diff`` tool), and runs it via
    :func:`invoke_summary_agent`. Transient failures retry this lane
    alone. The sandbox is never stopped here — the workflow's
    ``finally`` owns the stop.

    ``model_call_limit`` / ``tool_call_limit`` are the per-run agent
    caps computed by the workflow from the PR's size
    (:func:`app.services.review.helpers.compute_review_limits`) and
    applied to the built middleware stack.
    """
    sandbox = await _connect_sandbox(
        sandbox_id=sandbox_id,
        sandbox_name=sandbox_name,
        repo_id=repo_id,
        user_id=user_id,
    )

    model = build_chat_model(config=llm_config)
    backend = AsyncE2BSandbox(sandbox=sandbox.sandbox, workdir="/home/user")

    middleware = build_review_middleware(
        model_call_run_limit=model_call_limit,
        tool_call_run_limit=tool_call_limit,
    )

    agent = build_summary_agent(
        model=model,
        backend=backend,
        tools=[
            make_get_diff_tool(sandbox=sandbox, pr_number=pr_number, head_sha=head_sha)
        ],
        middleware=middleware,
    )

    prompt_payload = _build_prompt_payload(
        repo_name=repo_name,
        repo_id=repo_id,
        user_id=user_id,
        pr_number=pr_number,
        head_sha=head_sha,
    )

    log.info(
        "invoking summarizer agent step: repo=%s user=%s pr_number=%s",
        repo_name,
        user_id,
        pr_number,
    )

    return await invoke_summary_agent(agent, prompt_payload)


@DBOS.step(
    retries_allowed=True,
    max_attempts=3,
    should_retry=_SHOULD_RETRY_AGENT,
    backoff_rate=2,
)
async def invoke_comments_agent_step(
    *,
    sandbox_id: str,
    sandbox_name: str,
    repo_id: str,
    repo_name: str,
    user_id: str,
    pr_number: int,
    head_sha: str,
    llm_config: LLMConfig,
    model_call_limit: int,
    tool_call_limit: int,
) -> tuple[str, dict[str, UsageMetadata]]:
    """Durable step: run the comments lane and return
    ``(findings_report_text, usage)``. Same semantics as
    :func:`invoke_summary_agent_step`.
    """

    # Sandbox

    sandbox = await _connect_sandbox(
        sandbox_id=sandbox_id,
        sandbox_name=sandbox_name,
        repo_id=repo_id,
        user_id=user_id,
    )

    # Chat Model

    model = build_chat_model(config=llm_config)

    # Sandbox Backed

    backend = AsyncE2BSandbox(sandbox=sandbox.sandbox, workdir="/home/user")

    # Deep Agent

    middleware = build_review_middleware(
        model_call_run_limit=model_call_limit,
        tool_call_run_limit=tool_call_limit,
    )

    agent = build_comments_agent(
        model=model,
        backend=backend,
        tools=[
            make_get_diff_tool(sandbox=sandbox, pr_number=pr_number, head_sha=head_sha)
        ],
        middleware=middleware,
    )

    # Prompt

    prompt_payload = _build_prompt_payload(
        repo_name=repo_name,
        repo_id=repo_id,
        user_id=user_id,
        pr_number=pr_number,
        head_sha=head_sha,
    )

    log.info(
        "invoking comments agent step: repo=%s user=%s pr_number=%s",
        repo_name,
        user_id,
        pr_number,
    )

    # Invoke Agent

    return await invoke_comments_agent(agent, prompt_payload)


# --------------------------------------------------------------------------- #
# Outcome combination (pure)                                                   #
# --------------------------------------------------------------------------- #

AGENT_LANES: tuple[Literal["summarizer"], Literal["comments"]] = (
    "summarizer",
    "comments",
)
"""The two lane names, in the deterministic gather order."""

AgentStepOutcome = tuple[str, dict[str, UsageMetadata]] | BaseException
"""Outcome of one research-agent step: ``(raw_text, usage)`` or an exception."""

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
    its token usage (from the extractor step) or a ``BaseException`` —
    a per-lane :class:`AgentInvocationError` from the research agent,
    or a :class:`SummaryExtractionError` /
    :class:`CommentsExtractionError` /
    :class:`ReviewAgentRateLimitedError` from the extractor step.
    """

    summarizer: SummaryLaneOutcome
    comments: CommentsLaneOutcome


# Defaults for failed lanes: an empty summary string and an empty
# comment list. The summary column is non-null, so an empty string is
# valid; the review body then carries no summary text for that run.
_DEFAULT_SUMMARY: str = ""
_DEFAULT_COMMENTS_MODEL: type[ReviewComments] = ReviewComments


async def run_extractor_lanes(
    *,
    agent_results: Sequence[AgentStepOutcome],
    extractor_config: LLMConfig,
) -> ExtractorLaneResults:
    """Run the structured-extractor steps for the lanes that succeeded.

    ``agent_results`` holds the two :func:`asyncio.gather` outcomes in
    the deterministic order of :data:`AGENT_LANES`. Each entry is
    either ``(raw_text, usage)`` from a successful research lane or a
    per-lane :class:`AgentInvocationError`.

    For every successful lane the matching durable extractor step
    (:func:`extract_summary_result_step` /
    :func:`extract_comments_result_step`) is awaited (sequentially —
    each is a single structured-output call); an extractor failure is
    captured as the lane's outcome so the workflow's combine step can
    degrade the lane. Failed agent lanes carry their error through
    unchanged. The extractor steps' own transient-error retries happen
    inside the steps, so a captured exception here is always terminal
    for that lane.

    Returns a fully typed :class:`ExtractorLaneResults` mapping each
    lane to its outcome.
    """
    summary_agent_outcome = agent_results[0]
    comments_agent_outcome = agent_results[1]

    summary_lane: SummaryLaneOutcome
    if isinstance(summary_agent_outcome, BaseException):
        summary_lane = summary_agent_outcome
    else:
        raw_text, _usage = summary_agent_outcome
        try:
            summary_lane = await extract_summary_result_step(
                extractor_config=extractor_config,
                raw_text=raw_text,
            )
        except BaseException as exc:
            summary_lane = exc

    comments_lane: CommentsLaneOutcome
    if isinstance(comments_agent_outcome, BaseException):
        comments_lane = comments_agent_outcome
    else:
        raw_text, _usage = comments_agent_outcome
        try:
            comments_lane = await extract_comments_result_step(
                extractor_config=extractor_config,
                raw_text=raw_text,
            )
        except BaseException as exc:
            comments_lane = exc

    return ExtractorLaneResults(
        summarizer=summary_lane,
        comments=comments_lane,
    )


def combine_agent_outcomes(
    lane_outcomes: ExtractorLaneResults,
    *,
    pr_number: int,
    head_sha: str,
    repo_id: str,
    user_id: str,
    llm_config: LLMConfig,
    workflow_id: str,
) -> tuple[ReviewResult, TotalUsagesPerPR]:
    """Partition the lane outcomes and combine them into a review.

    ``lane_outcomes`` is the fully typed :class:`ExtractorLaneResults`
    mapping each lane to either ``(result, usage)`` (a validated
    structured payload from the extractor step, plus the aggregated
    agent + extractor usage) or a ``BaseException`` (a per-lane
    :class:`AgentInvocationError` from the research agent, or a
    :class:`SummaryExtractionError` /
    :class:`CommentsExtractionError` /
    :class:`ReviewAgentRateLimitedError` from the extractor step).

    Behaviour:

    - Both lanes failed → raises
      :class:`ReviewAgentsInvocationError` (captured to Sentry first).
      Each lane already exhausted its own step retries by now, so the
      workflow is marked ERROR.
    - Partial failure → failed lane degrades to an empty default
      (``""`` summary / ``ReviewComments(List=[])``), a warning is
      logged for the failed lane, and the review is built from the
      successful lane.

    Token usage is aggregated from the successful lanes only.
    """
    failures: list[tuple[str, BaseException]] = []
    summary_markdown: str = _DEFAULT_SUMMARY
    comments: ReviewComments = _DEFAULT_COMMENTS_MODEL(List=[])

    total_usages_per_pr = TotalUsagesPerPR(
        pr_number=pr_number,
        head_sha=head_sha,
        repo_id=repo_id,
        user_id=user_id,
        usages={},
    )

    summarizer_value = lane_outcomes["summarizer"]
    if isinstance(summarizer_value, BaseException):
        failures.append(("summarizer", summarizer_value))
    else:
        summary_result, summary_usage = summarizer_value
        summary_markdown = summary_result.summary
        _accumulate_usage(total_usages_per_pr["usages"], summary_usage)

    comments_value = lane_outcomes["comments"]
    if isinstance(comments_value, BaseException):
        failures.append(("comments", comments_value))
    else:
        comments_result, comments_usage = comments_value
        comments = comments_result
        _accumulate_usage(total_usages_per_pr["usages"], comments_usage)

    if len(failures) == len(AGENT_LANES):
        for lane, failed in failures:
            log.error(
                "review agents total failure: lane=%s retryable=%s cause=%r "
                "pr_number=%s head_sha=%s",
                lane,
                _failure_retryable(failed),
                _failure_cause(failed),
                pr_number,
                head_sha[:7],
            )
        err = ReviewAgentsInvocationError(
            user_id=user_id,
            repo_id=repo_id,
            pr_number=pr_number,
            head_sha=head_sha,
            llm_config=llm_config,
            workflow_id=workflow_id,
            failed_agents=[cast(StepError, failed) for _lane, failed in failures],
            succeeded_agents=[
                lane for lane in AGENT_LANES if lane not in {f[0] for f in failures}
            ],
            occurred_at=datetime.now(UTC),
        )
        _capture_review_agents_error_to_sentry(err)
        raise err

    if failures:
        for lane, failed in failures:
            log.warning(
                "review agents partial failure: lane=%s retryable=%s cause=%r "
                "pr_number=%s head_sha=%s",
                lane,
                _failure_retryable(failed),
                _failure_cause(failed),
                pr_number,
                head_sha[:7],
            )

    return (
        combine_review_results(
            summary_markdown=summary_markdown,
            comments=comments,
        ),
        total_usages_per_pr,
    )


def _accumulate_usage(
    buckets: dict[str, TotalUsages],
    usage: dict[str, UsageMetadata],
) -> None:
    """Accumulate one lane's per-model usage into the run's usage buckets.

    ``buckets`` is the ``usages`` map of a :class:`TotalUsagesPerPR`
    envelope; each model gets a :class:`TotalUsages` counter with the
    input / output / total token counts and the cache details merged.
    """
    for model_name, per_model in usage.items():
        bucket = buckets.setdefault(
            model_name,
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
        bucket["input_tokens"] += per_model.get("input_tokens", 0)
        bucket["output_tokens"] += per_model.get("output_tokens", 0)
        bucket["total_tokens"] += per_model.get("total_tokens", 0)
        details = per_model.get("input_token_details") or {}
        prev_cache_read = bucket["input_token_details"].get("cache_read")
        prev_cache_creation = bucket["input_token_details"].get("cache_creation")
        bucket["input_token_details"]["cache_read"] = (
            prev_cache_read if prev_cache_read is not None else 0
        ) + (details.get("cache_read") or 0)
        bucket["input_token_details"]["cache_creation"] = (
            prev_cache_creation if prev_cache_creation is not None else 0
        ) + (details.get("cache_creation") or 0)


def _failure_retryable(failure: BaseException) -> bool:
    """The lane failure's retryable flag, when it has one."""
    return bool(getattr(failure, "retryable", False))


def _failure_cause(failure: BaseException) -> str:
    """The lane failure's underlying cause, when it carries one."""
    cause = getattr(failure, "cause_exception", None)
    return repr(cause) if cause is not None else repr(failure)


def _capture_review_agents_error_to_sentry(
    err: ReviewAgentsInvocationError,
) -> None:
    """Push ``err`` to Sentry with the full run context as tags and extras.

    The aggregate event surfaces every field a production dashboard
    needs to attribute the failure: PR number, short and full head
    SHA, user id, LLM provider/model, failed/succeeded agent names,
    retryable flag per agent, workflow id, occurred_at, and the
    per-agent original cause. Failed lanes may be per-subagent
    :class:`AgentInvocationError` instances or the extractor steps'
    :class:`StepError` variants; the per-lane extras are read with
    attribute fallbacks so both kinds serialize identically.

    Sentry is observability, not a hard dependency: any failure from
    the capture path is swallowed after logging so it never masks the
    real error being raised to the workflow.
    """
    try:
        with sentry_sdk.push_scope() as scope:
            scope.set_tag("pr.number", str(err.pr_number))
            scope.set_tag("pr.head_sha", err.head_sha)
            scope.set_tag("pr.head_sha_short", err.head_sha[:7])
            scope.set_tag("user.id", err.user_id)
            scope.set_tag("llm.provider", err.llm_provider)
            scope.set_tag("llm.model", err.llm_model)
            scope.set_tag("agent.failed_count", str(len(err.failed_agents)))
            scope.set_tag("agent.succeeded_count", str(len(err.succeeded_agents)))
            scope.set_extra("repo_id", err.repo_id)
            scope.set_extra("llm.base_url", err.llm_base_url)
            scope.set_extra("workflow_id", err.workflow_id)
            scope.set_extra("occurred_at", err.occurred_at.isoformat())
            scope.set_extra(
                "failed_agents",
                [
                    {
                        "name": _failure_name(e),
                        "retryable": _failure_retryable(e),
                        "cause": repr(getattr(e, "cause_exception", e)),
                    }
                    for e in err.failed_agents
                ],
            )
            scope.set_extra("succeeded_agents", list(err.succeeded_agents))
            sentry_sdk.capture_exception(err)
    except Exception:
        log.exception("failed to capture ReviewAgentsInvocationError to Sentry")


def _failure_name(failure: BaseException) -> str:
    """The lane failure's name, when it has one."""
    return getattr(failure, "name", None) or type(failure).__name__


__all__ = [
    "AGENT_LANES",
    "AgentStepOutcome",
    "CommentsLaneOutcome",
    "ExtractedComments",
    "ExtractedSummary",
    "ExtractorLaneResults",
    "SummaryLaneOutcome",
    "combine_agent_outcomes",
    "invoke_comments_agent",
    "invoke_comments_agent_step",
    "invoke_summary_agent",
    "invoke_summary_agent_step",
    "run_extractor_lanes",
]
