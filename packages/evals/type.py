from typing import Annotated, Literal

from pydantic import BaseModel, Field

CommentSeverityStr = Literal["P1_CRITICAL", "P2_WARNING", "P3_NITPICK"]
CommentSideStr = Literal["RIGHT", "LEFT"]
ReviewVerdictStr = Literal["APPROVE", "COMMENT", "REQUEST_CHANGES"]


class EvalReviewComment(BaseModel):
    """One inline review comment in the eval response."""

    file_name: str
    comment: str
    severity: CommentSeverityStr
    from_line: int = Field(ge=0)
    to_line: int = Field(ge=0)
    side: CommentSideStr
    node_type: str | None = None


class EvalReviewUsage(BaseModel):
    """Per-model token usage for the run (one bucket per model name)."""

    input_tokens: int
    output_tokens: int
    total_tokens: int


class EvalReviewResponse(BaseModel):
    """What ``POST /review`` returns on success.

    ``workflow_id`` is the deterministic
    ``review:{repo_id}:{pr_number}:{head_sha[:7]}`` id, so duplicate
    POSTs for the same head SHA dedupe in DBOS and the second caller
    receives the first run's cached result. ``comments`` are sorted
    P1_CRITICAL → P2_WARNING → P3_NITPICK by the workflow's combine step.
    """

    workflow_id: str
    verdict: ReviewVerdictStr
    summary: str
    comments: Annotated[list[EvalReviewComment], Field(default_factory=list)]
    usages: Annotated[dict[str, EvalReviewUsage], Field(default_factory=dict)]
