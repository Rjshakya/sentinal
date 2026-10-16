"""Dataset metrics: per-PR scores plus the full-set roll-up."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from agents.judge import JudgeResult


class PrScore(BaseModel):
    """Score for one dataset entry."""

    model_config = ConfigDict(frozen=True)

    caseId: str = Field(default="")
    prUrl: str = Field(default="")
    title: str = Field(default="")
    confidence: float = Field(ge=0.0, le=1.0)
    matchedCount: int = Field(ge=0)
    totalGoldenCount: int = Field(ge=0)
    falsePositiveCount: int = Field(ge=0)
    generatedCount: int = Field(ge=0)
    recall: float = Field(ge=0.0, le=1.0)
    error: str | None = Field(default=None)

    def summary(self) -> str:
        baseSummary = (
            f"{self.caseId} confidence={self.confidence:.3f} "
            f"matched={self.matchedCount}/{self.totalGoldenCount} "
            f"falsePositives={self.falsePositiveCount} "
            f"generated={self.generatedCount} "
            f"recall={self.recall:.3f}"
        )
        if self.error is not None:
            return f"{baseSummary} error={self.error}"
        return baseSummary


class DatasetMetrics(BaseModel):
    """Dataset-level roll-up printed after every run. No files written."""

    model_config = ConfigDict(frozen=True)

    cases: int = Field(ge=0)
    meanConfidence: float = Field(ge=0.0, le=1.0)
    meanRecall: float = Field(ge=0.0, le=1.0)
    totalMatched: int = Field(ge=0)
    totalGolden: int = Field(ge=0)
    totalFalsePositives: int = Field(ge=0)
    totalGenerated: int = Field(ge=0)
    failedIds: Annotated[list[str], Field(default_factory=list)]
    items: Annotated[list[PrScore], Field(default_factory=list)]

    def summary(self) -> str:
        return (
            f"cases={self.cases} "
            f"meanConfidence={self.meanConfidence:.3f} "
            f"meanRecall={self.meanRecall:.3f} "
            f"matched={self.totalMatched}/{self.totalGolden} "
            f"falsePositives={self.totalFalsePositives} "
            f"generated={self.totalGenerated}"
        )


def computeRecall(matchedCount: int, totalGoldenCount: int, generatedCount: int) -> float:
    if totalGoldenCount > 0:
        return matchedCount / totalGoldenCount
    if generatedCount == 0:
        return 1.0
    return 0.0


def scoreSingleResult(
    judgeResult: JudgeResult, *, caseId: str, prUrl: str, title: str
) -> PrScore:
    """Build one per-PR score from a judge result."""
    return PrScore(
        caseId=caseId,
        prUrl=prUrl,
        title=title,
        confidence=judgeResult.confidence,
        matchedCount=judgeResult.matchedCount,
        totalGoldenCount=judgeResult.totalGoldenCount,
        falsePositiveCount=judgeResult.falsePositiveCount,
        generatedCount=judgeResult.generatedCount,
        recall=computeRecall(
            judgeResult.matchedCount, judgeResult.totalGoldenCount, judgeResult.generatedCount
        ),
        error=None,
    )


def failedPrScore(caseId: str, prUrl: str, title: str, reason: str) -> PrScore:
    """Zero score for a PR whose review or judge step failed."""
    return PrScore(
        caseId=caseId,
        prUrl=prUrl,
        title=title,
        confidence=0.0,
        matchedCount=0,
        totalGoldenCount=0,
        falsePositiveCount=0,
        generatedCount=0,
        recall=0.0,
        error=reason,
    )


def meanOfValues(values: Sequence[float]) -> float:
    valueList = list(values)
    if not valueList:
        return 0.0
    return sum(valueList) / len(valueList)


def createDatasetMetrics(itemScores: Sequence[PrScore]) -> DatasetMetrics:
    """Roll per-PR scores into dataset-level metrics."""
    scoreList = list(itemScores)
    caseTotal = len(scoreList)
    if caseTotal == 0:
        return DatasetMetrics(
            cases=0,
            meanConfidence=0.0,
            meanRecall=0.0,
            totalMatched=0,
            totalGolden=0,
            totalFalsePositives=0,
            totalGenerated=0,
            failedIds=[],
            items=[],
        )
    failedIds = [item.caseId for item in scoreList if item.error is not None]
    return DatasetMetrics(
        cases=caseTotal,
        meanConfidence=meanOfValues([item.confidence for item in scoreList]),
        meanRecall=meanOfValues([item.recall for item in scoreList]),
        totalMatched=sum(item.matchedCount for item in scoreList),
        totalGolden=sum(item.totalGoldenCount for item in scoreList),
        totalFalsePositives=sum(item.falsePositiveCount for item in scoreList),
        totalGenerated=sum(item.generatedCount for item in scoreList),
        failedIds=failedIds,
        items=scoreList,
    )


__all__ = [
    "DatasetMetrics",
    "PrScore",
    "createDatasetMetrics",
    "failedPrScore",
    "scoreSingleResult",
]
