"""Agent contract: shared outputs and run errors.

``ReviewOutput`` is what ``ReviewAgent.run()`` returns for one PR and
what the judge plus metrics consume. ``AgentRunError`` is the error
value for expected agent failures (LLM build failure, sandbox failure,
empty pipeline) -- callers discriminate with ``isinstance``.
"""

from __future__ import annotations

from typing import Annotated

from app.utils.schema import (
    CodeCommentDraft,
    ReviewVerdictStr,
)
from app.workflows.review_v2.types import TotalUsagesPerPR
from pydantic import BaseModel, ConfigDict, Field


class ReviewOutput(BaseModel):
    """Review result for one PR: verdict, summary, inline comments."""

    model_config = ConfigDict(frozen=True)

    verdict: ReviewVerdictStr
    summary: str = Field(default="")
    comments: Annotated[list[CodeCommentDraft], Field(default_factory=list)]
    model: str = Field(default="")
    usages: TotalUsagesPerPR | None = Field(default=None)


class AgentRunError(BaseModel):
    """Expected agent failure, returned as a value (never raised)."""

    model_config = ConfigDict(frozen=True)

    message: str
    agent: str = Field(default="")
    case_id: str = Field(default="")
    retryable: bool = Field(default=False)

    def __str__(self) -> str:
        return self.message


__all__ = ["AgentRunError", "ReviewOutput"]
