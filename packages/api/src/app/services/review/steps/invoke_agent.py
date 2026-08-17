"""DBOS durable steps that actually run the review agents.

This module owns the two per-agent steps, plus the helpers used to
wire each review agent to the E2B sandbox and the pure helper that
combines their outcomes.

Two parallel steps:

- :func:`invoke_summary_agent_step` — summarizer (markdown text).
- :func:`invoke_comments_agent_step` — comments (pydantic
  :class:`ReviewComments` with mixed severities).

Each step reconnects to the shared E2B sandbox by id, builds its
own chat model and deep-agent (with the shared ``get_diff`` tool),
runs it via the :func:`invoke_<name>_agent` wrappers (which
translate any failure into the per-agent error class with a
``retryable`` flag), and returns ``(result, usage)``. Steps are
started concurrently from the workflow body with
``asyncio.gather(..., return_exceptions=True)`` — the documented
DBOS parallel-steps pattern — and a transient failure (429 / 5xx /
timeout) retries **that lane alone** (``max_attempts=3``,
``backoff_rate=2``) instead of re-running both agents.

:func:`combine_agent_outcomes` then partitions the two results:

- both lanes failed → raises
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

import json
import logging
import re
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from typing import Any

import sentry_sdk
from dbos import DBOS
from langchain_core.callbacks import get_usage_metadata_callback
from langchain_core.messages import UsageMetadata
from langchain_e2b import AsyncE2BSandbox
from pydantic import BaseModel

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
    AgentInvocationError,
    CommentsAgentInvocationError,
    ReviewAgentCrashedError,
    ReviewAgentsInvocationError,
    SandboxConnectError,
    SubagentInvocationError,
    SummaryAgentInvocationError,
    is_llm_retry_error,
)
from app.services.review.middleware import build_review_middleware
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

_FENCED_JSON_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)
"""Matches a fenced code block that may carry a ``json`` language tag."""


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


def _parse_json_text(text: str) -> dict[str, Any]:
    """Parse the first JSON object out of free-form model text.

    Tries, in order: the whole trimmed message, a fenced ```json
    block, and the substring between the first ``{`` and the last
    ``}``. Raises ``ValueError`` when nothing parses.
    """
    stripped = text.strip()
    if not stripped:
        raise ValueError("agent returned an empty final message")
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        pass
    fence = _FENCED_JSON_RE.search(stripped)
    if fence is not None:
        try:
            return json.loads(fence.group(1).strip())
        except json.JSONDecodeError:
            pass
    start, end = stripped.find("{"), stripped.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(stripped[start : end + 1])
        except json.JSONDecodeError:
            pass
    raise ValueError(f"could not parse JSON from agent output: {stripped[:200]!r}")


def _extract_structured(result: Any, model_cls: type[BaseModel]) -> Any:
    """Extract and validate the lane's structured payload.

    Preferred source is the runtime's ``structured_response`` (the
    schema tool call). When the agent ends with plain text instead —
    or when ``response_format`` was dropped for an endpoint that
    rejects forced tool choice — the last AI message is parsed as
    JSON and validated against ``model_cls``.
    """
    if isinstance(result, dict) and result.get("structured_response") is not None:
        return model_cls.model_validate(result["structured_response"])
    data = _parse_json_text(_last_ai_text(result))
    if "List" not in data and "list" in data:
        # The comment models' field is `List` (capital L); models
        # occasionally emit lowercase `list` despite the contract.
        data = dict(data)
        data["List"] = data.pop("list")
    return model_cls.model_validate(data)


def _summary_extractor(result: Any) -> SummaryResult:
    """Validate the summarizer's structured payload.

    Accepts the runtime's ``structured_response`` (a
    :class:`SummaryResult`) or, when the model ended with text, JSON
    parsed from the final message. Mirrors the structured extractor
    of the comments agent.
    """
    return _extract_structured(result, SummaryResult)


def _comments_extractor(result: Any) -> ReviewComments:
    """Validate the comments agent's structured payload."""
    return _extract_structured(result, ReviewComments)


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


async def invoke_comments_agent(
    agent: DeepAgentGraph, prompt_payload: dict[str, Any]
) -> tuple[ReviewComments, dict[str, UsageMetadata]]:
    """Run the comments subagent; on failure raise
    :class:`CommentsAgentInvocationError`."""
    return await _call_with_error_wrapping(
        agent=agent,
        prompt_payload=prompt_payload,
        error_cls=CommentsAgentInvocationError,
        result_extractor=_comments_extractor,
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

    middleware = build_review_middleware()

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
) -> tuple[ReviewComments, dict[str, UsageMetadata]]:
    """Durable step: run the comments lane and return
    ``(ReviewComments, usage)``. Same semantics as
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

    middleware = build_review_middleware()

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

AGENT_LANES: tuple[str, ...] = ("summarizer", "comments")
"""The two lane names, in the deterministic gather order."""

# Defaults for failed lanes: an empty summary string and an empty
# comment list. The summary column is non-null, so an empty string is
# valid; the review body then carries no summary text for that run.
_DEFAULT_SUMMARY: str = ""
_DEFAULT_COMMENTS_MODEL: type[ReviewComments] = ReviewComments


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
    """Partition the two gather results and combine them into a review.

    ``results`` holds the two :func:`asyncio.gather` outcomes in the
    deterministic order of :data:`AGENT_LANES` (the order the steps
    were started in). Each entry is either ``(result, usage)`` from a
    successful lane, a per-lane :class:`AgentInvocationError`, or —
    defensively — any other ``BaseException``.

    Behaviour:

    - Both lanes failed → raises
      :class:`ReviewAgentsInvocationError` (captured to Sentry first).
      Each lane already exhausted its own step retries by now, so the
      workflow is marked ERROR.
    - Partial failure → failed lane degrades to an empty default
      (``""`` summary / ``ReviewComments(List=[])``), a warning is
      logged for the failed lane (name, cause, retryable), and the
      review is built from the successful lane.
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

    if len(failures) == len(AGENT_LANES):
        for failed in failures:
            log.error(
                "review agents total failure: lane=%s retryable=%s cause=%r "
                "pr_number=%s head_sha=%s",
                failed.name,
                failed.retryable,
                failed.cause_exception,
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
            failed_agents=failures,
            succeeded_agents=list(successes.keys()),
            occurred_at=datetime.now(UTC),
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
        if "comments" not in successes:
            successes["comments"] = _DEFAULT_COMMENTS_MODEL(List=[])

    return (
        combine_review_results(
            summary_markdown=successes["summarizer"],
            comments=successes["comments"],
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
    "invoke_comments_agent",
    "invoke_comments_agent_step",
    "invoke_summary_agent",
    "invoke_summary_agent_step",
]
