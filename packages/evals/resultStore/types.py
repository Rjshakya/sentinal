"""Result store contract: per-PR evaluations plus the file envelope.

``evaluations.json`` holds run metadata, the dataset roll-up, and one
entry per PR (score, judge verdict, generated vs golden comments, and
the resolved SHAs). The model id lives in the directory name
(``results/{modelId}/evaluations.json``) and is not repeated in the file.
"""

from __future__ import annotations

from typing import Annotated

from app.utils.schema import CodeCommentDraft
from datasetLoader.types import GoldenComment, PrContext
from pydantic import BaseModel, ConfigDict, Field

from agents.judge import JudgeResult
from metrics.scoring import DatasetMetrics, PrScore


class ResolvedRef(BaseModel):
    """Resolved SHAs and branches for one PR. Empty when resolution failed."""

    model_config = ConfigDict(frozen=True)

    baseSha: str = Field(default="")
    headSha: str = Field(default="")
    baseBranch: str = Field(default="")
    headBranch: str = Field(default="")


class PrEvaluation(BaseModel):
    """Stored evaluation for one dataset entry."""

    model_config = ConfigDict(frozen=True)

    caseId: str = Field(default="")
    prUrl: str = Field(default="")
    title: str = Field(default="")
    prScore: PrScore
    judgeResult: JudgeResult | None = Field(default=None)
    generatedComments: Annotated[list[CodeCommentDraft], Field(default_factory=list)]
    goldenComments: Annotated[list[GoldenComment], Field(default_factory=list)]
    resolved: ResolvedRef = Field(default_factory=ResolvedRef)
    error: str | None = Field(default=None)


class EvaluationsFile(BaseModel):
    """What ``results/{modelId}/evaluations.json`` holds."""

    model_config = ConfigDict(frozen=True)

    createdAt: str = Field(min_length=1)
    datasetPath: str = Field(min_length=1)
    env: str = Field(min_length=1)
    datasetMetrics: DatasetMetrics
    evaluations: Annotated[list[PrEvaluation], Field(default_factory=list)]


class ResultStoreError(BaseModel):
    """Result store failure, returned as a value (never raised)."""

    model_config = ConfigDict(frozen=True)

    message: str
    path: str | None = None

    def __str__(self) -> str:
        return self.message


def buildResolvedRef(prContext: PrContext | None) -> ResolvedRef:
    if prContext is None:
        return ResolvedRef()
    return ResolvedRef(
        baseSha=prContext.baseSha,
        headSha=prContext.headSha,
        baseBranch=prContext.baseBranch,
        headBranch=prContext.headBranch,
    )


__all__ = [
    "EvaluationsFile",
    "PrEvaluation",
    "ResolvedRef",
    "ResultStoreError",
    "buildResolvedRef",
]
