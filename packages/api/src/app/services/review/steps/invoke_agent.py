"""DBOS durable steps that actually run the review agents.

This module owns the four per-lane agent steps, plus the helpers
used to wire each review agent to the E2B sandbox and the pure
helper that combines their outcomes.

Four parallel steps:

- :func:`invoke_summary_agent_step` — summarizer (markdown text).
- :func:`invoke_security_agent_step` — security (pydantic
  :class:`SecurityComments`).
- :func:`invoke_correctness_agent_step` — correctness (pydantic
  :class:`CorrectnessComments`).
- :func:`invoke_style_agent_step` — style (pydantic
  :class:`StyleComments`).

Each step reconnects to the shared E2B sandbox by id, builds its
own chat model and deep-agent (with the shared ``get_diff`` tool),
runs it via the :func:`invoke_<name>_agent` wrappers (which
translate any failure into the per-lane error class with a
``retryable`` flag), and returns ``(result, usage)``. Steps are
started concurrently from the workflow body with
``asyncio.gather(..., return_exceptions=True)`` — the documented
DBOS parallel-steps pattern — and a transient failure (429 / 5xx /
timeout) retries **that lane alone** (``max_attempts=3``,
``backoff_rate=2``) instead of re-running all four agents.

:func:`combine_agent_outcomes` then partitions the four results:

- all four lanes failed → raises
  :class:`app.services.review.errors.ReviewAgentsInvocationError`
  (pushed to Sentry with the full run context before raising);
- partial failure → failed lanes degrade to empty defaults (``""``
  summary / empty comment lists) with a warning log and the review
  completes with the successful lanes' output.

The invoke steps never stop the sandbox: four concurrent steps
share one sandbox, so only the workflow's ``finally``
:func:`app.services.review.steps.stop_sandbox.stop_sandbox_step`
stops it.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import datetime, timezone
from typing import Any, Callable

import sentry_sdk
from dbos import DBOS
from langchain_core.callbacks import get_usage_metadata_callback
from langchain_core.messages import UsageMetadata
from langchain_e2b import AsyncE2BSandbox

from app.core.llm import LLMConfig, build_chat_model
from app.core.sandbox.e2b import E2BSandbox
from app.services.agent.models import (
    CorrectnessComments,
    ReviewResult,
    SecurityComments,
    StyleComments,
    SummaryResult,
)
from app.services.review._internal import _SHOULD_RETRY_AGENT, _e2b_spec
from app.services.review.agent import (
    assemble_user_prompt,
    build_correctness_agent,
    build_security_agent,
    build_style_agent,
    build_summary_agent,
    combine_review_results,
)
from app.services.review.errors import (
    AgentInvocationError,
    CorrectnessAgentInvocationError,
    ReviewAgentCrashedError,
    ReviewAgentsInvocationError,
    SandboxConnectError,
    SecurityAgentInvocationError,
    StyleAgentInvocationError,
    SubagentInvocationError,
    SummaryAgentInvocationError,
    is_llm_retry_error,
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


def _summary_extractor(result: Any) -> SummaryResult:
    """Validate the summarizer's ``structured_response`` payload.

    Returns the markdown block from the ``summary`` field. Mirrors the
    structured extractors of the three severity specialists.
    """
    return SummaryResult.model_validate(result["structured_response"])


def _security_extractor(result: Any) -> SecurityComments:
    """Validate the security subagent's ``structured_response`` payload."""
    return SecurityComments.model_validate(result["structured_response"])


def _correctness_extractor(result: Any) -> CorrectnessComments:
    """Validate the correctness subagent's ``structured_response`` payload."""
    return CorrectnessComments.model_validate(result["structured_response"])


def _style_extractor(result: Any) -> StyleComments:
    """Validate the style subagent's ``structured_response`` payload."""
    return StyleComments.model_validate(result["structured_response"])


async def _call_with_error_wrapping(
    *,
    agent: DeepAgentGraph,
    prompt_payload: dict[str, Any],
    error_cls: type[SubagentInvocationError],
    result_extractor: Callable[[Any], Any],
) -> tuple[Any, dict[str, UsageMetadata]]:
    """Run ``agent.ainvoke`` and translate any failure into ``error_cls``.

    The wrapper performs two things:

    1. Calls the subagent's ``ainvoke`` and applies ``result_extractor``
       to convert the raw output into the structured payload the caller
       expects (markdown text for the summary agent, a validated
       pydantic model for the three structured agents).
    2. Catches any exception (LLM 5xx/429/timeout from
       :func:`is_llm_retry_error`, validation errors, post-processing
       errors) and re-raises it as an instance of ``error_cls`` with a
       ``retryable`` flag and any recoverable details (message kinds
       from the partial result). The original exception is preserved
       via ``raise ... from exc`` so Sentry's exception chain and
       Python's ``__cause__`` both work.
    """
    result: Any = None
    try:
        with get_usage_metadata_callback() as usage_cb:
            result = await agent.ainvoke(prompt_payload)
            usage = usage_cb.usage_metadata

        return result_extractor(result), usage

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
) -> tuple[SummaryResult, dict[str, UsageMetadata]]:
    """Run the summarizer subagent; on failure raise
    :class:`SummaryAgentInvocationError`."""
    return await _call_with_error_wrapping(
        agent=agent,
        prompt_payload=prompt_payload,
        error_cls=SummaryAgentInvocationError,
        result_extractor=_summary_extractor,
    )


async def invoke_security_agent(
    agent: Any, prompt_payload: dict[str, Any]
) -> tuple[SecurityComments, dict[str, UsageMetadata]]:
    """Run the security subagent; on failure raise
    :class:`SecurityAgentInvocationError`."""
    return await _call_with_error_wrapping(
        agent=agent,
        prompt_payload=prompt_payload,
        error_cls=SecurityAgentInvocationError,
        result_extractor=_security_extractor,
    )


async def invoke_correctness_agent(
    agent: Any, prompt_payload: dict[str, Any]
) -> tuple[CorrectnessComments, dict[str, UsageMetadata]]:
    """Run the correctness subagent; on failure raise
    :class:`CorrectnessAgentInvocationError`."""
    return await _call_with_error_wrapping(
        agent=agent,
        prompt_payload=prompt_payload,
        error_cls=CorrectnessAgentInvocationError,
        result_extractor=_correctness_extractor,
    )


async def invoke_style_agent(
    agent: Any, prompt_payload: dict[str, Any]
) -> tuple[StyleComments, dict[str, UsageMetadata]]:
    """Run the style subagent; on failure raise
    :class:`StyleAgentInvocationError`."""
    return await _call_with_error_wrapping(
        agent=agent,
        prompt_payload=prompt_payload,
        error_cls=StyleAgentInvocationError,
        result_extractor=_style_extractor,
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
) -> dict[str, Any]:
    """Build the user message payload sent to every review agent."""
    user_prompt = assemble_user_prompt(
        repo_name=repo_name,
        repo_id=repo_id,
        user_id=user_id,
        pr_number=pr_number,
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
) -> tuple[str, dict[str, UsageMetadata]]:
    """Durable step: run the summarizer lane and return ``(markdown, usage)``.

    Reconnects to the E2B sandbox by id, builds the summarizer
    deep-agent (own chat model + ``get_diff`` tool), and runs it via
    :func:`invoke_summary_agent`. Transient failures retry this lane
    alone. The sandbox is never stopped here — the workflow's
    ``finally`` owns the stop.
    """
    sandbox = await _connect_sandbox(
        sandbox_id=sandbox_id,
        sandbox_name=sandbox_name,
        repo_id=repo_id,
        user_id=user_id,
    )
    model = build_chat_model(config=llm_config)
    backend = AsyncE2BSandbox(sandbox=sandbox.sandbox, workdir="/home/user")
    agent = build_summary_agent(
        model=model,
        backend=backend,
        tools=[
            make_get_diff_tool(sandbox=sandbox, pr_number=pr_number, head_sha=head_sha)
        ],
    )
    prompt_payload = _build_prompt_payload(
        repo_name=repo_name,
        repo_id=repo_id,
        user_id=user_id,
        pr_number=pr_number,
    )

    log.info(
        "invoking summarizer agent step: repo=%s user=%s pr_number=%s",
        repo_name,
        user_id,
        pr_number,
    )

    summary, usage = await invoke_summary_agent(agent, prompt_payload)
    return summary.summary, usage


@DBOS.step(
    retries_allowed=True,
    max_attempts=3,
    should_retry=_SHOULD_RETRY_AGENT,
    backoff_rate=2,
)
async def invoke_security_agent_step(
    *,
    sandbox_id: str,
    sandbox_name: str,
    repo_id: str,
    repo_name: str,
    user_id: str,
    pr_number: int,
    head_sha: str,
    llm_config: LLMConfig,
) -> tuple[SecurityComments, dict[str, UsageMetadata]]:
    """Durable step: run the security lane and return
    ``(SecurityComments, usage)``. Same semantics as
    :func:`invoke_summary_agent_step`.
    """
    sandbox = await _connect_sandbox(
        sandbox_id=sandbox_id,
        sandbox_name=sandbox_name,
        repo_id=repo_id,
        user_id=user_id,
    )
    model = build_chat_model(config=llm_config)
    backend = AsyncE2BSandbox(sandbox=sandbox.sandbox, workdir="/home/user")
    agent = build_security_agent(
        model=model,
        backend=backend,
        tools=[
            make_get_diff_tool(sandbox=sandbox, pr_number=pr_number, head_sha=head_sha)
        ],
    )
    prompt_payload = _build_prompt_payload(
        repo_name=repo_name,
        repo_id=repo_id,
        user_id=user_id,
        pr_number=pr_number,
    )

    log.info(
        "invoking security agent step: repo=%s user=%s pr_number=%s",
        repo_name,
        user_id,
        pr_number,
    )
    return await invoke_security_agent(agent, prompt_payload)


@DBOS.step(
    retries_allowed=True,
    max_attempts=3,
    should_retry=_SHOULD_RETRY_AGENT,
    backoff_rate=2,
)
async def invoke_correctness_agent_step(
    *,
    sandbox_id: str,
    sandbox_name: str,
    repo_id: str,
    repo_name: str,
    user_id: str,
    pr_number: int,
    head_sha: str,
    llm_config: LLMConfig,
) -> tuple[CorrectnessComments, dict[str, UsageMetadata]]:
    """Durable step: run the correctness lane and return
    ``(CorrectnessComments, usage)``. Same semantics as
    :func:`invoke_summary_agent_step`.
    """
    sandbox = await _connect_sandbox(
        sandbox_id=sandbox_id,
        sandbox_name=sandbox_name,
        repo_id=repo_id,
        user_id=user_id,
    )
    model = build_chat_model(config=llm_config)
    backend = AsyncE2BSandbox(sandbox=sandbox.sandbox, workdir="/home/user")
    agent = build_correctness_agent(
        model=model,
        backend=backend,
        tools=[
            make_get_diff_tool(sandbox=sandbox, pr_number=pr_number, head_sha=head_sha)
        ],
    )
    prompt_payload = _build_prompt_payload(
        repo_name=repo_name,
        repo_id=repo_id,
        user_id=user_id,
        pr_number=pr_number,
    )

    log.info(
        "invoking correctness agent step: repo=%s user=%s pr_number=%s",
        repo_name,
        user_id,
        pr_number,
    )
    return await invoke_correctness_agent(agent, prompt_payload)


@DBOS.step(
    retries_allowed=True,
    max_attempts=3,
    should_retry=_SHOULD_RETRY_AGENT,
    backoff_rate=2,
)
async def invoke_style_agent_step(
    *,
    sandbox_id: str,
    sandbox_name: str,
    repo_id: str,
    repo_name: str,
    user_id: str,
    pr_number: int,
    head_sha: str,
    llm_config: LLMConfig,
) -> tuple[StyleComments, dict[str, UsageMetadata]]:
    """Durable step: run the style lane and return ``(StyleComments, usage)``.

    Same semantics as :func:`invoke_summary_agent_step`.
    """
    sandbox = await _connect_sandbox(
        sandbox_id=sandbox_id,
        sandbox_name=sandbox_name,
        repo_id=repo_id,
        user_id=user_id,
    )
    model = build_chat_model(config=llm_config)
    backend = AsyncE2BSandbox(sandbox=sandbox.sandbox, workdir="/home/user")
    agent = build_style_agent(
        model=model,
        backend=backend,
        tools=[
            make_get_diff_tool(sandbox=sandbox, pr_number=pr_number, head_sha=head_sha)
        ],
    )
    prompt_payload = _build_prompt_payload(
        repo_name=repo_name,
        repo_id=repo_id,
        user_id=user_id,
        pr_number=pr_number,
    )

    log.info(
        "invoking style agent step: repo=%s user=%s pr_number=%s",
        repo_name,
        user_id,
        pr_number,
    )
    return await invoke_style_agent(agent, prompt_payload)


# --------------------------------------------------------------------------- #
# Outcome combination (pure)                                                   #
# --------------------------------------------------------------------------- #

AGENT_LANES: tuple[str, ...] = ("summarizer", "security", "correctness", "style")
"""The four lane names, in the deterministic gather order."""

# Defaults for failed lanes: an empty summary string and empty comment
# lists. The summary column is non-null, so an empty string is valid;
# the review body then carries no summary text for that run.
_DEFAULT_SUMMARY: str = ""
_DEFAULT_COMMENT_LANES: dict[
    str, type[SecurityComments | CorrectnessComments | StyleComments]
] = {
    "security": SecurityComments,
    "correctness": CorrectnessComments,
    "style": StyleComments,
}


def combine_agent_outcomes(
    results: Sequence[Any],
    *,
    pr_number: int,
    head_sha: str,
    repo_id: str,
    user_id: str,
    llm_config: LLMConfig,
    workflow_id: str,
) -> tuple[ReviewResult, TotalUsagesPerPR]:
    """Partition the four gather results and combine them into a review.

    ``results`` holds the four :func:`asyncio.gather` outcomes in the
    deterministic order of :data:`AGENT_LANES` (the order the steps
    were started in). Each entry is either ``(result, usage)`` from a
    successful lane, a per-lane :class:`AgentInvocationError`, or —
    defensively — any other ``BaseException``.

    Behaviour:

    - All four lanes failed → raises
      :class:`ReviewAgentsInvocationError` (captured to Sentry first).
      Each lane already exhausted its own step retries by now, so the
      workflow is marked ERROR.
    - Partial failure → failed lanes degrade to empty defaults
      (``""`` summary / ``*Comments(List=[])``), a warning is logged
      per failed lane (name, cause, retryable), and the review is
      built from the successful lanes.
    - Unexpected ``BaseException`` (programming bug) → raises
      :class:`ReviewAgentCrashedError`.

    Token usage is aggregated from the successful lanes only.
    """
    successes: dict[str, Any] = {}
    failures: list[AgentInvocationError] = []

    total_usages_per_pr = TotalUsagesPerPR(
        pr_number=pr_number,
        head_sha=head_sha,
        repo_id=repo_id,
        user_id=user_id,
        usages={},
    )

    for agent_name, value in zip(AGENT_LANES, results):
        if isinstance(value, AgentInvocationError):
            failures.append(value)
        elif isinstance(value, BaseException):
            # Defensive: the wrappers only raise AgentInvocationError
            # subclasses, so anything else here is a programming bug.
            # Re-raise as a non-retryable error so DBOS marks the
            # workflow as ERROR without retrying.
            log.exception(
                "review agents saw unexpected exception type from "
                "subagent wrapper: name=%s exc_type=%s",
                agent_name,
                type(value).__name__,
            )
            raise ReviewAgentCrashedError(
                cause=f"{type(value).__name__}: {value}"
            ) from value
        else:
            agent_result, agent_usage = value
            successes[agent_name] = agent_result

            for model_name, usage in agent_usage.items():
                bucket = total_usages_per_pr["usages"].setdefault(
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
                bucket["input_tokens"] += usage.get("input_tokens", 0)
                bucket["output_tokens"] += usage.get("output_tokens", 0)
                bucket["total_tokens"] += usage.get("total_tokens", 0)
                details = usage.get("input_token_details") or {}
                prev_cache_read = bucket["input_token_details"].get("cache_read")
                prev_cache_creation = bucket["input_token_details"].get(
                    "cache_creation"
                )
                bucket["input_token_details"]["cache_read"] = (
                    prev_cache_read if prev_cache_read is not None else 0
                ) + (details.get("cache_read") or 0)
                bucket["input_token_details"]["cache_creation"] = (
                    prev_cache_creation if prev_cache_creation is not None else 0
                ) + (details.get("cache_creation") or 0)

    if len(failures) == 4:
        err = ReviewAgentsInvocationError(
            user_id=user_id,
            repo_id=repo_id,
            pr_number=pr_number,
            head_sha=head_sha,
            llm_config=llm_config,
            workflow_id=workflow_id,
            failed_agents=failures,
            succeeded_agents=list(successes.keys()),
            occurred_at=datetime.now(timezone.utc),
        )
        _capture_review_agents_error_to_sentry(err)
        raise err

    if failures:
        for failed in failures:
            log.warning(
                "review agents partial failure: lane=%s retryable=%s cause=%r "
                "pr_number=%s head_sha=%s",
                failed.name,
                failed.retryable,
                failed.cause_exception,
                pr_number,
                head_sha[:7],
            )
        if "summarizer" not in successes:
            successes["summarizer"] = _DEFAULT_SUMMARY
        for lane, model_cls in _DEFAULT_COMMENT_LANES.items():
            if lane not in successes:
                successes[lane] = model_cls(List=[])

    return (
        combine_review_results(
            summary_markdown=successes["summarizer"],
            security=successes["security"],
            correctness=successes["correctness"],
            style=successes["style"],
        ),
        total_usages_per_pr,
    )


def _capture_review_agents_error_to_sentry(
    err: ReviewAgentsInvocationError,
) -> None:
    """Push ``err`` to Sentry with the full run context as tags and extras.

    The aggregate event surfaces every field a production dashboard
    needs to attribute the failure: PR number, short and full head
    SHA, user id, LLM provider/model, failed/succeeded agent names,
    retryable flag per agent, workflow id, occurred_at, and the
    per-agent original cause. Per-subagent
    :class:`AgentInvocationError` instances ride along as the
    exception chain (``__context__``) because each one is raised
    ``from exc`` inside its wrapper.

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
                        "name": e.name,
                        "retryable": e.retryable,
                        "cause": repr(e.cause_exception),
                    }
                    for e in err.failed_agents
                ],
            )
            scope.set_extra("succeeded_agents", list(err.succeeded_agents))
            sentry_sdk.capture_exception(err)
    except Exception:
        log.exception("failed to capture ReviewAgentsInvocationError to Sentry")


__all__ = [
    "AGENT_LANES",
    "combine_agent_outcomes",
    "invoke_correctness_agent",
    "invoke_correctness_agent_step",
    "invoke_security_agent",
    "invoke_security_agent_step",
    "invoke_style_agent",
    "invoke_style_agent_step",
    "invoke_summary_agent",
    "invoke_summary_agent_step",
]
