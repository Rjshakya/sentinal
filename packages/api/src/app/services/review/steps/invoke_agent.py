"""Invoke the review deep-agent and parse its structured response."""

from __future__ import annotations

import logging

from app.services.agent.models import ReviewResult
from app.services.review.agent import (
    assemble_user_prompt,
)
from app.services.review.errors import (
    ReviewAgentCrashedError,
    ReviewAgentRateLimitedError,
    extract_retry_after_seconds,
    is_llm_transient_error,
)
from app.services.review.helpers import parse_review_response
from app.services.review.types import DeepAgentGraph

log = logging.getLogger(__name__)


async def invoke_review_agent(
    *,
    agent: DeepAgentGraph,
    repo_name: str,
    repo_id: str,
    user_id: str,
    pr_number: int,
) -> ReviewResult:
    """Invoke the review agent and parse its structured response.

    Raises:
        ReviewAgentRateLimitedError: the LLM returned 429 / 5xx / a
            timeout — a :class:`TransientStepError` that DBOS retries
            up to ``max_attempts`` times.
        ReviewAgentCrashedError: any other exception raised by
            ``agent.ainvoke`` — treated as a final business outcome
            and not retried.
        ReviewAgentReturnedNoStructuredResponseError: the agent
            finished but produced no ``structured_response`` payload.
    """
    user_prompt = assemble_user_prompt(
        repo_name=repo_name,
        repo_id=repo_id,
        user_id=user_id,
        pr_number=pr_number,
    )
    log.info(
        "invoking review agent: repo=%s user=%s pr_number=%s",
        repo_name,
        user_id,
        pr_number,
    )
    try:
        raw = await agent.ainvoke(
            {"messages": [{"role": "user", "content": user_prompt}]}
        )
    except Exception as exc:
        if is_llm_transient_error(exc):
            wait = extract_retry_after_seconds(exc)
            log.warning(
                "review agent transient: repo=%s pr_number=%s wait_s=%s cause=%s",
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
            "review agent crashed: repo=%s pr_number=%s",
            repo_name,
            pr_number,
        )
        raise ReviewAgentCrashedError(
            cause=f"{type(exc).__name__}: {exc}"
        ) from exc

    return parse_review_response(raw)


__all__ = ["invoke_review_agent"]
