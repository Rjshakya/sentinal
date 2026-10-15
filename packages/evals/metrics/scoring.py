"""Dataset-level metrics: per-item scores plus the full-set roll-up."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from agents.judge import JudgeVerdict
from datasets.types import GoldOutput


class ItemScore(BaseModel):
    """Score for one ``inputs[i]`` / ``outputs[i]`` pair."""

    model_config = ConfigDict(frozen=True)

    case_id: str = Field(default="")
    precision: float = Field(ge=0.0, le=1.0)
    recall: float = Field(ge=0.0, le=1.0)
    f1: float = Field(ge=0.0, le=1.0)
    fp_rate: float = Field(ge=0.0, le=1.0)
    verdict_match: bool = Field(default=False)
    matched: int = Field(default=0, ge=0)
    predicted: int = Field(default=0, ge=0)
    gold_total: int = Field(default=0, ge=0)
    error: str | None = Field(default=None)


class DatasetReport(BaseModel):
    """What ``report.json`` holds: per-item scores plus the roll-up."""

    model_config = ConfigDict(frozen=True)

    cases: int = Field(ge=0)
    mean_precision: float = Field(ge=0.0, le=1.0)
    mean_recall: float = Field(ge=0.0, le=1.0)
    mean_f1: float = Field(ge=0.0, le=1.0)
    mean_fp_rate: float = Field(ge=0.0, le=1.0)
    verdict_accuracy: float = Field(ge=0.0, le=1.0)
    failed_ids: Annotated[list[str], Field(default_factory=list)]
    items: Annotated[list[ItemScore], Field(default_factory=list)]

    def summary(self) -> str:
        return (
            f"cases={self.cases} "
            f"precision={self.mean_precision:.3f} "
            f"recall={self.mean_recall:.3f} "
            f"f1={self.mean_f1:.3f} "
            f"fp_rate={self.mean_fp_rate:.3f} "
            f"verdict_acc={self.verdict_accuracy:.3f}"
        )


def scoreOne(
    verdict: JudgeVerdict, gold: GoldOutput, *, case_id: str = ""
) -> ItemScore:
    """Derive precision / recall / F1 / FP rate from one judge verdict."""
    gold_n = len(gold.bugs)
    predicted_n = len(verdict.comments)
    matched = sum(1 for c in verdict.comments if c.matched_gold_idx is not None)
    fp = sum(1 for c in verdict.comments if c.verdict == "false_positive")

    precision = matched / predicted_n if predicted_n else 0.0
    recall = matched / gold_n if gold_n else (1.0 if predicted_n == 0 else 0.0)
    f1 = (
        2 * precision * recall / (precision + recall)
        if (precision + recall) > 0
        else 0.0
    )
    fp_rate = fp / predicted_n if predicted_n else 0.0
    return ItemScore(
        case_id=case_id,
        precision=precision,
        recall=recall,
        f1=f1,
        fp_rate=fp_rate,
        verdict_match=verdict.verdict_matches_gold,
        matched=matched,
        predicted=predicted_n,
        gold_total=gold_n,
    )


def failedItem(case_id: str, *, reason: str) -> ItemScore:
    """Zero score for a case whose agent run failed."""
    return ItemScore(
        case_id=case_id,
        precision=0.0,
        recall=0.0,
        f1=0.0,
        fp_rate=0.0,
        verdict_match=False,
        matched=0,
        predicted=0,
        gold_total=0,
        error=reason,
    )


def createMetrics(items: Sequence[ItemScore]) -> DatasetReport:
    """Roll per-item scores into the dataset-level report."""
    item_list = list(items)
    n = len(item_list)
    if n == 0:
        return DatasetReport(
            cases=0,
            mean_precision=0.0,
            mean_recall=0.0,
            mean_f1=0.0,
            mean_fp_rate=0.0,
            verdict_accuracy=0.0,
            failed_ids=[],
            items=[],
        )
    mean = lambda vals: sum(vals) / n if n else 0.0
    failed_ids = [
        item.case_id for item in item_list if item.error is not None or item.f1 <= 0
    ]
    return DatasetReport(
        cases=n,
        mean_precision=mean([i.precision for i in item_list]),
        mean_recall=mean([i.recall for i in item_list]),
        mean_f1=mean([i.f1 for i in item_list]),
        mean_fp_rate=mean([i.fp_rate for i in item_list]),
        verdict_accuracy=mean([1.0 if i.verdict_match else 0.0 for i in item_list]),
        failed_ids=failed_ids,
        items=item_list,
    )


__all__ = ["DatasetReport", "ItemScore", "createMetrics", "failedItem", "scoreOne"]
