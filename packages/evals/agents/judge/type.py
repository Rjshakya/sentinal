"""Judge contract: gold dataset, structured verdict schema, and the report shape.

The judge compares the review output (``result_md``) against the gold
dataset (``output.json``). It does not receive the diff — the eval no
longer materialises one locally. The diff is irrelevant to grading:
the gold bugs already encode the substance the reviewer is graded on,
and the comments anchor themselves on lines the reviewer can see.
"""

from typing import Annotated, Literal

from pydantic import BaseModel, Field

from type import EvalReviewResponse

GoldSeverity = Literal["P1_CRITICAL", "P2_WARNING", "P3_NITPICK"]


class GoldBug(BaseModel):
    """One ground-truth finding in the dataset ``output.json``."""

    id: str
    bug: str
    location: str
    severity: GoldSeverity


class GoldOutput(BaseModel):
    """The dataset ``output.json``: the expected verdict and bugs."""

    verdict: Literal["APPROVE", "COMMENT", "REQUEST_CHANGES"]
    bugs: Annotated[list[GoldBug], Field(default_factory=list)]


class JudgeCommentVerdict(BaseModel):
    """The judge's verdict on one predicted comment."""

    comment_idx: int
    verdict: Literal["real_bug", "nitpick", "false_positive"]
    matched_gold_idx: int | None = None
    severity_matches: bool | None = None
    reason: str


class JudgeSummaryVerdict(BaseModel):
    """The judge's verdict on the review summary."""

    faithful: bool
    concise: bool
    missing_key_risks: Annotated[list[str], Field(default_factory=list)]


class JudgeVerdict(BaseModel):
    """The full structured judgement for one review run."""

    verdict_matches_gold: bool
    comments: Annotated[list[JudgeCommentVerdict], Field(default_factory=list)]
    summary: JudgeSummaryVerdict
    overall_reasoning: str


class JudgeInput(BaseModel):
    """Everything the judge agent needs: gold + the review's result.md."""

    gold: GoldOutput
    review: EvalReviewResponse


class JudgeReport(BaseModel):
    """What ``report/<pr-id>/report.json`` holds: the verdict plus derived metrics."""

    judge_model: str
    verdict: JudgeVerdict
    precision: float
    recall: float
    f1: float
    fp_rate: float


def compute_metrics(
    verdict: JudgeVerdict, gold: GoldOutput
) -> tuple[float, float, float, float]:
    """Derive precision / recall / F1 / FP rate from the judge's matches."""
    gold_n = len(gold.bugs)
    predicted_n = len(verdict.comments)
    matched = sum(1 for c in verdict.comments if c.matched_gold_idx is not None)
    fp = sum(1 for c in verdict.comments if c.verdict == "false_positive")

    precision = matched / predicted_n if predicted_n else 0.0
    recall = matched / gold_n if gold_n else (1.0 if predicted_n == 0 else 0.0)
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    fp_rate = fp / predicted_n if predicted_n else 0.0
    return precision, recall, f1, fp_rate


__all__ = [
    "GoldBug",
    "GoldOutput",
    "JudgeCommentVerdict",
    "JudgeInput",
    "JudgeReport",
    "JudgeSummaryVerdict",
    "JudgeVerdict",
    "compute_metrics",
]
