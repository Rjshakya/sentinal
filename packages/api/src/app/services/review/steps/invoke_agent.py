"""Invoke the review deep-agent and parse its structured response."""

from __future__ import annotations

import logging

from app.core.result import Err, Ok, Result
from app.services.agent.models import ReviewResult
from app.services.review.agent import (
    assemble_user_prompt,
)
from app.services.review.errors import (
    ReviewAgentCrashed,
    ReviewAgentReturnedNoStructuredResponse,
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
) -> Result[
    ReviewResult,
    ReviewAgentCrashed | ReviewAgentReturnedNoStructuredResponse,
]:
    """Invoke the review agent and parse its structured response.

    The single ``try / except`` in this step is the boundary into the
    deepagents SDK: any exception raised by ``agent.ainvoke`` is
    converted to :class:`ReviewAgentCrashed` so the orchestrator never
    has to handle an exception from this layer.
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
        log.exception(
            "review agent crashed: repo=%s pr_number=%s",
            repo_name,
            pr_number,
        )
        return Err(ReviewAgentCrashed(cause=f"{type(exc).__name__}: {exc}"))

    log.info("raw review result: %s", raw)
    return parse_review_response(raw)


__all__: list[str] = ["invoke_review_agent"]
