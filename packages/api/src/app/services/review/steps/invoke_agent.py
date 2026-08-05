"""DBOS durable steps that actually run the review agents.

This module owns the active parallel-fanout step, plus the small
helpers used to wire the four review agents to the E2B sandbox.

- :func:`invoke_review_agents_step` (active, parallel) — runs the
  four review agents (``summary`` / ``security`` / ``correctness`` /
  ``style``) concurrently via :func:`asyncio.gather`, combines their
  results, and aggregates per-model token usage into a
  :class:`app.services.review.workflow_types.TotalUsagesPerPR`
  envelope. Each subagent is wrapped in its own
  :func:`invoke_<name>_agent` helper that translates any failure
  into the per-subagent error class with a ``retryable`` flag.
  Failures are aggregated into
  :class:`app.services.review.errors.ReviewAgentsInvocationError`
  and pushed to Sentry before being raised.

Per-subagent wrappers:

- :func:`invoke_summary_agent` — summarizer (markdown text).
- :func:`invoke_security_agent` — security (pydantic
  :class:`SecurityComments`).
- :func:`invoke_correctness_agent` — correctness (pydantic
  :class:`CorrectnessComments`).
- :func:`invoke_style_agent` — style (pydantic
  :class:`StyleComments`).

Helpers:

- :func:`_capture_review_agents_error_to_sentry` — pushes an
  aggregate :class:`ReviewAgentsInvocationError` to Sentry with the
  full run context as tags and extras.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Callable

import sentry_sdk
from dbos import DBOS
from langchain_core.callbacks import get_usage_metadata_callback
from langchain_core.messages import UsageMetadata

from app.core.llm import LLMConfig
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
    build_review_agents,
    combine_review_results,
    create_review_llm_models,
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


def _summary_extractor(result: Any) -> str:
    """Validate the summarizer's ``structured_response`` payload.

    Returns the markdown block from the ``summary`` field. Mirrors the
    structured extractors of the three severity specialists.
    """
    return SummaryResult.model_validate(result["structured_response"]).summary


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
) -> tuple[str, dict[str, UsageMetadata]]:
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
# Parallel-fanout step (active)                                                  #
# --------------------------------------------------------------------------- #


@DBOS.step(
    retries_allowed=True,
    max_attempts=2,
    should_retry=_SHOULD_RETRY_AGENT,
    backoff_rate=2,
)
async def invoke_review_agents_step(
    *,
    sandbox_id: str,
    sandbox_name: str,
    repo_id: str,
    repo_name: str,
    user_id: str,
    pr_number: int,
    head_sha: str,
    llm_config: LLMConfig,
) -> tuple[ReviewResult, TotalUsagesPerPR]:
    """Durable step: run the four review agents in parallel and combine.

    The fan-out:

    1. Reconnects to the E2B sandbox (one connection for the step).
    2. Builds the chat model and the four review agents (summary,
       security, correctness, style) — all sharing the same
       ``AsyncE2BSandbox`` backend and the same shared tool
       (``get_diff``). Comment-line validation is prompt-driven: each
       specialist reads ``diff.json`` (the hunk map written by
       :func:`app.services.review.diff.parse_and_write_diff_json`) and
       self-checks / re-anchors its draft anchors before emitting them.
    3. Each subagent runs in its own :func:`invoke_<name>_agent`
       wrapper. The wrapper translates any exception (LLM crash, rate
       limit, or unparseable output) into the per-subagent error class
       (``SummaryAgentInvocationError`` etc.) with a ``retryable``
       flag set from :func:`is_llm_retry_error`.
    4. ``asyncio.gather(..., return_exceptions=True)`` runs all four
       wrappers concurrently. Failures are partitioned into
       ``failed_agents``; successes are passed to
       :func:`combine_review_results`.
    5. When any subagent fails, the step raises
       :class:`ReviewAgentsInvocationError` carrying the full run
       context (user, repo, pr, head_sha, LLM provider/model/base URL,
       workflow id, failed-agent list, succeeded-agent list, and the
       UTC timestamp of the failure). The exception is also pushed to
       Sentry before being raised, with the same fields attached as
       tags and extras so production dashboards can attribute the
       failure without cross-referencing logs.

    The whole step is a single DBOS checkpoint: a crash mid-fan-out
    resumes from the cached result, so transient failures don't re-run
    the LLM. The sandbox is stopped in a ``finally`` so a parse /
    combine failure does not leak the connection.

    Raises:
        SandboxConnectError: reconnect to E2B failed. Transient —
            DBOS retries.
        ReviewAgentsInvocationError: one or more subagents failed.
            Retried by DBOS when any failing subagent has
            ``retryable=True``; otherwise final.
    """
    spec = _e2b_spec()
    try:
        sandbox = await E2BSandbox.connect(
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

    try:
        # create review models

        review_models = create_review_llm_models(llm_config=llm_config)

        (
            summary_agent,
            security_agent,
            correctness_agent,
            style_agent,
        ) = build_review_agents(
            sandbox=sandbox,
            pr_number=pr_number,
            head_sha=head_sha,
            models=review_models,
        )

        user_prompt = assemble_user_prompt(
            repo_name=repo_name,
            repo_id=repo_id,
            user_id=user_id,
            pr_number=pr_number,
        )

        prompt_payload = {"messages": [{"role": "user", "content": user_prompt}]}

        log.info(
            "invoking review agents (parallel): repo=%s user=%s pr_number=%s",
            repo_name,
            user_id,
            pr_number,
        )

        results = await asyncio.gather(
            invoke_summary_agent(summary_agent, prompt_payload),
            invoke_security_agent(security_agent, prompt_payload),
            invoke_correctness_agent(correctness_agent, prompt_payload),
            invoke_style_agent(style_agent, prompt_payload),
            return_exceptions=True,
        )

        summary_value, security_value, correctness_value, style_value = results

        successes: dict[str, Any] = {}
        failures: list[AgentInvocationError] = []

        total_usages_per_pr = TotalUsagesPerPR(
            pr_number=pr_number,
            head_sha=head_sha,
            repo_id=repo_id,
            user_id=user_id,
            usages={},
        )

        for agent_name, value in (
            ("summarizer", summary_value),
            ("security", security_value),
            ("correctness", correctness_value),
            ("style", style_value),
        ):
            if isinstance(value, AgentInvocationError):
                failures.append(value)
            elif isinstance(value, BaseException):
                # Defensive: the wrappers only raise AgentInvocationError
                # subclasses, so anything else here is a programming bug.
                # Re-raise as a non-retryable step error so DBOS marks the
                # workflow as ERROR without retrying.

                log.exception(
                    "review agents step saw unexpected exception type from "
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

        if failures:
            err = ReviewAgentsInvocationError(
                user_id=user_id,
                repo_id=repo_id,
                pr_number=pr_number,
                head_sha=head_sha,
                llm_config=llm_config,
                workflow_id=DBOS.workflow_id or "<no-workflow-id>",
                failed_agents=failures,
                succeeded_agents=list(successes.keys()),
                occurred_at=datetime.now(timezone.utc),
            )
            _capture_review_agents_error_to_sentry(err)
            raise err

        return combine_review_results(
            summary_markdown=successes["summarizer"],
            security=successes["security"],
            correctness=successes["correctness"],
            style=successes["style"],
        ), total_usages_per_pr
    finally:
        try:
            await sandbox.stop()
        except Exception:
            log.exception("failed to stop sandbox after agent invocation")


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
    "invoke_correctness_agent",
    "invoke_review_agents_step",
    "invoke_security_agent",
    "invoke_style_agent",
    "invoke_summary_agent",
]
