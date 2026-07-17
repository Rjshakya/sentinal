from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from e2b import AsyncSandbox

from app.core.result import Result
from app.core.sandbox import BaseSandbox
from app.services.agent.models import ReviewResult
from app.services.review.errors import (
    DiffUnavailable,
    ReviewAgentCrashed,
    ReviewAgentReturnedNoStructuredResponse,
)

# --------------------------------------------------------------------------- #
# result type                                                                 #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class ReviewRunResult:
    """What the orchestrator hands back to the router."""

    pr_id: str
    commit_id: str
    result: ReviewResult


# --------------------------------------------------------------------------- #
# ports                                                                       #
# --------------------------------------------------------------------------- #


class DiffProvider(Protocol):
    """Source of the unified diff the review agent reads."""

    async def get_diff(
        self,
        sandbox: BaseSandbox,
        *,
        repo_id: str,
        repo_name: str,
        base_sha: str,
        head_sha: str,
    ) -> Result[str, DiffUnavailable]: ...


class ReviewAgentRunner(Protocol):
    """LLM-SDK boundary for the review agent."""

    async def run(
        self,
        *,
        diff: str,
        repo_id: str,
        repo_name: str,
        user_id: str,
        sandbox: AsyncSandbox,
    ) -> Result[
        ReviewResult,
        ReviewAgentCrashed | ReviewAgentReturnedNoStructuredResponse,
    ]: ...
