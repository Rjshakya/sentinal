"""DBOS durable steps that actually run the review agents.

This module owns both the active parallel-fanout step and the
orchestrator-with-subagents step, plus the small helpers used to
wire them to the E2B sandbox.

- :func:`invoke_review_agents_step` (active, parallel) — runs the
  four review agents (``summary`` / ``security`` / ``correctness`` /
  ``style``) concurrently via :func:`asyncio.gather` and combines
  their results. Each subagent is wrapped in its own
  :func:`invoke_<name>_agent` helper that translates any failure
  into the per-subagent error class with a ``retryable`` flag.
  Failures are aggregated into
  :class:`app.services.review.errors.ReviewAgentsInvocationError`
  and pushed to Sentry before being raised.
- :func:`invoke_review_agent_step` (orchestrator) — runs the root
  deep-agent (the orchestrator) once, with the four subagents
  attached. The orchestrator delegates, absorbs subagent failures by
  substituting empty results, and emits a single
  :class:`app.services.agent.models.ReviewResult` as its structured
  response.

Per-subagent wrappers:

- :func:`invoke_summary_agent` — summarizer (markdown text).
- :func:`invoke_security_agent` — security (pydantic
  :class:`SecurityComments`).
- :func:`invoke_correctness_agent` — correctness (pydantic
  :class:`CorrectnessComments`).
- :func:`invoke_style_agent` — style (pydantic
  :class:`StyleComments`).

Helpers:

- :func:`_orchestrator_backend` — wraps the connected
  :class:`E2BSandbox` as a deepagents :class:`AsyncE2BSandbox` backend
  for filesystem / shell access.
- :func:`_orchestrator_tools` — returns the tools the orchestrator
  itself can call (currently just :func:`make_get_diff_tool`).
- :func:`_capture_review_agents_error_to_sentry` — pushes an
  aggregate :class:`ReviewAgentsInvocationError` to Sentry with the
  full run context as tags and extras.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Callable, cast

import sentry_sdk
from dbos import DBOS
from langchain_core.tools import BaseTool

from app.core.llm import LLMProviderStr, build_chat_model
from app.core.llm_callbacks import make_llm_io_handler
from app.core.sandbox.e2b import E2BSandbox
from app.services.agent.models import (
    CorrectnessComments,
    ReviewResult,
    SecurityComments,
    StyleComments,
)
from app.services.review._internal import _SHOULD_RETRY_AGENT, _e2b_spec
from app.services.review.agent import (
    assemble_user_prompt,
    build_orchestrator_agent,
    build_review_agents,
    build_review_subagents,
    combine_review_results,
    extract_last_ai_text,
    verdict_for,
)
from app.services.review.errors import (
    AgentInvocationError,
    CorrectnessAgentInvocationError,
    ReviewAgentCrashedError,
    ReviewAgentRateLimitedError,
    ReviewAgentsInvocationError,
    SandboxConnectError,
    SecurityAgentInvocationError,
    StyleAgentInvocationError,
    SubagentInvocationError,
    SummaryAgentInvocationError,
    extract_retry_after_seconds,
    is_llm_retry_error,
)
from app.services.review.tools import make_get_diff_tool

log = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Orchestrator helpers                                                          #
# --------------------------------------------------------------------------- #


def _orchestrator_backend(sandbox: E2BSandbox):  # type: ignore[no-untyped-def]
    """Wrap the E2B sandbox as a deepagents AsyncE2BSandbox backend.

    Imported lazily so this file doesn't pay the import cost on every
    step invocation outside this function.
    """
    from langchain_e2b import AsyncE2BSandbox

    return AsyncE2BSandbox(sandbox=sandbox.sandbox, workdir="/home/user")


def _orchestrator_tools(
    *,
    sandbox: E2BSandbox,
    pr_number: int,
    head_sha: str,
) -> list[BaseTool]:
    """Return the orchestrator's own tools (same as a subagent's).

    The orchestrator uses ``get_diff`` to read the diff first.
    Comment-line validation is prompt-driven: any anchor the
    orchestrator (or its subagents) cares to inspect is read directly
    from ``/home/user/tmp/{pr_number}/{head_sha}/diff.json`` in the
    sandbox via the deepagents backend's ``read_file`` tool. The
    orchestrator does not own a comment-anchor validation tool of its
    own. Subagents get the same tool independently (each in its own
    sandbox view).
    """
    return [
        make_get_diff_tool(sandbox=sandbox, pr_number=pr_number, head_sha=head_sha),
    ]


# --------------------------------------------------------------------------- #
# Per-subagent wrappers                                                         #
# --------------------------------------------------------------------------- #


def _summary_extractor(result: Any) -> str:
    """Return the last AI message's text from a summarizer ainvoke result."""
    return extract_last_ai_text(result)


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
    agent: Any,
    prompt_payload: dict[str, Any],
    error_cls: type[SubagentInvocationError],
    result_extractor: Callable[[Any], Any],
) -> Any:
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
        result = await agent.ainvoke(prompt_payload)
        return result_extractor(result)
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
    agent: Any, prompt_payload: dict[str, Any]
) -> str:
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
) -> SecurityComments:
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
) -> CorrectnessComments:
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
) -> StyleComments:
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
    provider: LLMProviderStr,
    llm_baseurl: str | None,
    llm_api_key: str,
    llm_model: str,
) -> ReviewResult:
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
        (
            summary_agent,
            security_agent,
            correctness_agent,
            style_agent,
            _,
            _,
        ) = build_review_agents(
            sandbox=sandbox,
            pr_number=pr_number,
            head_sha=head_sha,
            provider=provider,
            llm_baseurl=llm_baseurl,
            llm_api_key=llm_api_key,
            llm_model=llm_model,
            repo_id=repo_id,
            repo_name=repo_name,
            workflow_id=DBOS.workflow_id,
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
                successes[agent_name] = value

        if failures:
            err = ReviewAgentsInvocationError(
                user_id=user_id,
                repo_id=repo_id,
                pr_number=pr_number,
                head_sha=head_sha,
                llm_provider=provider,
                llm_model=llm_model,
                llm_base_url=llm_baseurl,
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
        )
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


# --------------------------------------------------------------------------- #
# Production step — orchestrator with subagents                                 #
# --------------------------------------------------------------------------- #


@DBOS.step(
    retries_allowed=True,
    max_attempts=2,
    backoff_rate=2,
)
async def invoke_review_agent_step(
    *,
    sandbox_id: str,
    sandbox_name: str,
    repo_id: str,
    repo_name: str,
    user_id: str,
    pr_number: int,
    head_sha: str,
    provider: LLMProviderStr,
    llm_baseurl: str | None,
    llm_api_key: str,
    llm_model: str,
) -> ReviewResult:
    """Durable step: run the orchestrator-with-subagents review and combine.

    The flow:

    1. Reconnects to the E2B sandbox (one connection for the step).
    2. Builds the orchestrator's chat model with a per-agent LLM I/O
       callback tagged ``agent="orchestrator"``.
    3. Builds four review subagents (summary, security, correctness,
       style) sharing the orchestrator's chat model.
    4. Builds the root deep-agent with the four subagents attached
       via ``subagents=[]``. The orchestrator's ``response_format`` is
       :class:`ReviewResult` directly.
    5. ``ainvoke``s the orchestrator once. The orchestrator delegates
       to the four subagents in turn, absorbs any subagent failure
       (substituting an empty result), and emits a single
       :class:`ReviewResult` as its structured response.
    6. Validates the structured response and overwrites the
       ``verdict`` field with the deterministic value
       :func:`verdict_for` (the orchestrator is told to set
       ``"COMMENT"``; the real verdict is recomputed here from the
       merged comments).

    Failure semantics:

    - The orchestrator absorbs subagent failures (its prompt tells it
      to substitute an empty result and continue). Therefore a single
      subagent's failure does NOT cause a DBOS step retry.
    - Orchestrator-level failures (LLM 5xx / 429 / timeout) raise
      :class:`ReviewAgentRateLimitedError`, which is transient; DBOS
      retries up to ``max_attempts`` times.
    - Orchestrator crashes (anything else) raise
      :class:`ReviewAgentCrashedError` (not retried).
    - A missing or unparseable structured response raises
      :class:`ReviewAgentReturnedNoStructuredResponseError` (not
      retried).

    The whole step is a single DBOS checkpoint: a crash mid-fanout
    resumes from the cached result, so transient failures don't re-run
    the LLM. The sandbox is stopped in a ``finally`` so a parse /
    combine failure does not leak the connection.

    Comment-line validation is prompt-driven: each specialist subagent
    reads the parallel ``diff.json`` file directly via the deepagents
    backend's ``read_file`` to self-validate and re-anchor its
    ``(file, line, side)`` anchors before emitting
    :class:`CodeCommentDraft` entries. The server-side
    :func:`app.services.review.hunk_map.filter_drafts` (called by the
    workflow after this step) is the final backstop.

    Raises:
        SandboxConnectError: reconnect to E2B failed. Transient —
            DBOS retries.
        ReviewAgentRateLimitedError: the orchestrator returned 429 /
            5xx / timeout. Transient — DBOS retries up to
            ``max_attempts`` times.
        ReviewAgentCrashedError: any other exception from
            ``orchestrator.ainvoke`` — business outcome, not retried.
        ReviewAgentReturnedNoStructuredResponseError: the
            orchestrator finished without ``structured_response``, or
            the response could not be validated as
            :class:`ReviewResult`. Business outcome, not retried.
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
            cause=(
                f"failed to reconnect sandbox for orchestrator: "
                f"{type(exc).__name__}: {exc}"
            ),
        ) from exc

    try:
        orchestrator_model = build_chat_model(
            provider=provider,
            base_url=llm_baseurl,
            api_key=llm_api_key,
            model=llm_model,
            headers={"cf-aig-gateway-id": "sentinal-ai-gateway"},
            callbacks=make_llm_io_handler(
                agent_name="orchestrator",
                repo_name=repo_name,
                repo_id=repo_id,
                pr_number=pr_number,
                head_sha=head_sha,
                workflow_id=DBOS.workflow_id,
                model=llm_model,
            ),
        )

        subagents = build_review_subagents(
            sandbox=sandbox,
            pr_number=pr_number,
            head_sha=head_sha,
            model=orchestrator_model,
        )

        orchestrator = build_orchestrator_agent(
            model=orchestrator_model,
            backend=cast(Any, _orchestrator_backend(sandbox)),
            subagents=subagents,
            tools=_orchestrator_tools(
                sandbox=sandbox,
                pr_number=pr_number,
                head_sha=head_sha,
            ),
        )
        user_prompt = assemble_user_prompt(
            repo_name=repo_name,
            repo_id=repo_id,
            user_id=user_id,
            pr_number=pr_number,
        )
        prompt_payload = {"messages": [{"role": "user", "content": user_prompt}]}
        log.info(
            "invoking review orchestrator: repo=%s user=%s pr_number=%s",
            repo_name,
            user_id,
            pr_number,
        )

        try:
            result = await orchestrator.ainvoke(prompt_payload)
        except Exception as exc:
            if is_llm_retry_error(exc):
                wait = extract_retry_after_seconds(exc)
                log.warning(
                    "review orchestrator transient: repo=%s pr_number=%s "
                    "wait_s=%s cause=%s",
                    repo_name,
                    pr_number,
                    wait,
                    exc,
                )
                raise ReviewAgentRateLimitedError(
                    cause=f"{type(exc).__name__}: {exc}",
                    retry_after_seconds=wait,
                ) from exc

            log.exception(
                "review orchestrator crashed: repo=%s pr_number=%s",
                repo_name,
                pr_number,
            )
            raise ReviewAgentCrashedError(cause=f"{type(exc).__name__}: {exc}") from exc

        if not isinstance(result, dict) or "structured_response" not in result:
            from app.services.agent.helpers import extract_message_kinds
            from app.services.review.errors import (
                ReviewAgentReturnedNoStructuredResponseError,
            )

            log.exception(
                "review orchestrator returned no structured_response: "
                "repo=%s pr_number=%s",
                repo_name,
                pr_number,
            )
            raise ReviewAgentReturnedNoStructuredResponseError(
                message_kinds=extract_message_kinds((result or {}).get("messages"))
            )

        try:
            review = ReviewResult.model_validate(result["structured_response"])
        except Exception as exc:
            from app.services.agent.helpers import extract_message_kinds
            from app.services.review.errors import (
                ReviewAgentReturnedNoStructuredResponseError,
            )

            log.exception(
                "review orchestrator returned unparseable output: repo=%s pr_number=%s",
                repo_name,
                pr_number,
            )
            raise ReviewAgentReturnedNoStructuredResponseError(
                message_kinds=extract_message_kinds((result or {}).get("messages"))
            ) from exc

        review.verdict = verdict_for(review.comments)
        return review
    finally:
        try:
            await sandbox.stop()
        except Exception:
            log.exception("failed to stop sandbox after orchestrator invocation")


__all__ = [
    "invoke_correctness_agent",
    "invoke_review_agent_step",
    "invoke_review_agents_step",
    "invoke_security_agent",
    "invoke_style_agent",
    "invoke_summary_agent",
]
