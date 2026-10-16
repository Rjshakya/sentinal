"""Judge agent: golden comments plus generated comments in, verdict out.

Golden comments hold only a body plus a severity label. Generated
comments carry file anchors plus body plus severity. The judge matches
by the same underlying issue even when wording differs, flags false
positives, and returns confidence from 0 to 1 with match counts.
"""

from __future__ import annotations

import json
from typing import Annotated

from app.services.llm.errors import LLMConfigError
from app.services.llm.service import createLLMModel
from app.services.llm.types import LLMCtx
from app.utils.schema import CodeCommentDraft
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, ConfigDict, Field

from agents.base import AgentRunError
from datasetLoader.types import GoldenComment

JUDGE_SYSTEM_PROMPT = """\
You are the evaluator for an AI code-review agent. You judge generated
review comments against golden comments (the truth).

You receive golden comments (each with body plus severity) and generated
comments (each with file, lines, body, severity).

For EACH generated comment (generatedIndex is its index in the list):
- Match it to a golden comment when both describe the SAME underlying
  issue. Wording may differ. Severity may differ. The substance must
  match: the same bug, the same risk, the same wrong behavior.
- A generated comment with no matching golden comment is a false
  positive: wrong claim, hallucinated issue, generic advice, duplicate
  of another generated comment, or a real nit that no golden comment
  covers.
- reason: one short paragraph that justifies the match or the false
  positive flag. Quote the shared issue in plain words.

For EACH golden comment, decide whether at least one generated comment
matches it. Count matched golden comments.

Then set confidence from 0 to 1:
- 1.0 means every golden issue is matched and no false positives exist.
- 0.0 means nothing matches or everything is noise.
- Penalize false positives hard. A false positive is worse than silence.
- Penalize missed golden comments proportionally.

Rules:
- Match by substance only. Golden comments carry no file or line.
- Never invent a match. Match only when the issue is the same.
- Do not reward comment count. Judge substance.
- Return valid structured output only.
"""


class JudgeMatch(BaseModel):
    """One golden comment matched by one generated comment."""

    model_config = ConfigDict(frozen=True)

    goldenIndex: int = Field(ge=0)
    generatedIndex: int = Field(ge=0)
    reason: str = Field(default="")


class JudgeFalsePositive(BaseModel):
    """One generated comment that matches no golden comment."""

    model_config = ConfigDict(frozen=True)

    generatedIndex: int = Field(ge=0)
    reason: str = Field(default="")


class JudgeDraft(BaseModel):
    """Raw structured output from the judge model."""

    model_config = ConfigDict(frozen=True)

    confidence: float = Field(ge=0.0, le=1.0)
    matches: Annotated[list[JudgeMatch], Field(default_factory=list)]
    falsePositives: Annotated[list[JudgeFalsePositive], Field(default_factory=list)]
    overallReasoning: str = Field(default="")


class JudgeResult(BaseModel):
    """Final judge verdict with derived counts. Counts come from code."""

    model_config = ConfigDict(frozen=True)

    confidence: float = Field(ge=0.0, le=1.0)
    matchedCount: int = Field(ge=0)
    totalGoldenCount: int = Field(ge=0)
    falsePositiveCount: int = Field(ge=0)
    generatedCount: int = Field(ge=0)
    matches: Annotated[list[JudgeMatch], Field(default_factory=list)]
    falsePositives: Annotated[list[JudgeFalsePositive], Field(default_factory=list)]
    overallReasoning: str = Field(default="")
    judgeModel: str = Field(default="")

    def summary(self) -> str:
        return (
            f"confidence={self.confidence:.3f} "
            f"matched={self.matchedCount}/{self.totalGoldenCount} "
            f"falsePositives={self.falsePositiveCount} "
            f"generated={self.generatedCount}"
        )


def buildJudgePayload(
    generatedComments: list[CodeCommentDraft], goldenComments: list[GoldenComment]
) -> dict[str, object]:
    return {
        "goldenComments": [
            {"index": index, **golden.model_dump(mode="json")}
            for index, golden in enumerate(goldenComments)
        ],
        "generatedComments": [
            {"index": index, **generated.model_dump(mode="json")}
            for index, generated in enumerate(generatedComments)
        ],
    }


def clampConfidence(rawConfidence: float) -> float:
    if rawConfidence != rawConfidence:  # NaN guard without importing math
        return 0.0
    if rawConfidence < 0.0:
        return 0.0
    if rawConfidence > 1.0:
        return 1.0
    return rawConfidence


def deduplicateMatches(rawMatches: list[JudgeMatch], goldenTotal: int, generatedTotal: int) -> list[JudgeMatch]:
    seenPairs: set[tuple[int, int]] = set()
    seenGolden: set[int] = set()
    cleanMatches: list[JudgeMatch] = []
    for match in rawMatches:
        if match.goldenIndex < 0 or match.goldenIndex >= goldenTotal:
            continue
        if match.generatedIndex < 0 or match.generatedIndex >= generatedTotal:
            continue
        pairKey = (match.goldenIndex, match.generatedIndex)
        if pairKey in seenPairs:
            continue
        if match.goldenIndex in seenGolden:
            continue
        seenPairs.add(pairKey)
        seenGolden.add(match.goldenIndex)
        cleanMatches.append(match)
    return sorted(cleanMatches, key=lambda match: (match.goldenIndex, match.generatedIndex))


def deduplicateFalsePositives(
    rawFalsePositives: list[JudgeFalsePositive],
    generatedTotal: int,
    matchedGenerated: set[int],
) -> list[JudgeFalsePositive]:
    seenGenerated: set[int] = set()
    cleanFalsePositives: list[JudgeFalsePositive] = []
    for falsePositive in rawFalsePositives:
        if falsePositive.generatedIndex < 0 or falsePositive.generatedIndex >= generatedTotal:
            continue
        if falsePositive.generatedIndex in matchedGenerated:
            continue
        if falsePositive.generatedIndex in seenGenerated:
            continue
        seenGenerated.add(falsePositive.generatedIndex)
        cleanFalsePositives.append(falsePositive)
    return sorted(cleanFalsePositives, key=lambda item: item.generatedIndex)


def buildJudgeResult(
    draft: JudgeDraft,
    goldenTotal: int,
    generatedTotal: int,
    judgeModel: str,
) -> JudgeResult:
    cleanMatches = deduplicateMatches(draft.matches, goldenTotal, generatedTotal)
    matchedGenerated: set[int] = {match.generatedIndex for match in cleanMatches}
    cleanFalsePositives = deduplicateFalsePositives(draft.falsePositives, generatedTotal, matchedGenerated)
    # Any generated comment that is neither matched nor flagged counts as noise.
    flaggedGenerated: set[int] = set(matchedGenerated) | {item.generatedIndex for item in cleanFalsePositives}
    implicitNoise = sorted(set(range(generatedTotal)) - flaggedGenerated)
    extendedFalsePositives = list(cleanFalsePositives)
    for generatedIndex in implicitNoise:
        # Only treat unmatched output as noise when golden comments exist.
        # Empty golden plus empty generated is a clean pass, not noise.
        if goldenTotal > 0:
            extendedFalsePositives.append(
                JudgeFalsePositive(generatedIndex=generatedIndex, reason="No golden comment covers this issue.")
            )
    extendedFalsePositives = sorted(extendedFalsePositives, key=lambda item: item.generatedIndex)
    # Empty golden set: confidence is 1 when nothing was generated, else 0.
    if goldenTotal == 0:
        derivedConfidence = 1.0 if generatedTotal == 0 else 0.0
    else:
        derivedConfidence = clampConfidence(draft.confidence)
    return JudgeResult(
        confidence=derivedConfidence,
        matchedCount=len(cleanMatches),
        totalGoldenCount=goldenTotal,
        falsePositiveCount=len(extendedFalsePositives),
        generatedCount=generatedTotal,
        matches=cleanMatches,
        falsePositives=extendedFalsePositives,
        overallReasoning=draft.overallReasoning,
        judgeModel=judgeModel,
    )


def coerceJudgeDraft(rawOutput: object) -> JudgeDraft | AgentRunError:
    try:
        if isinstance(rawOutput, JudgeDraft):
            return rawOutput
        if isinstance(rawOutput, dict):
            return JudgeDraft.model_validate(rawOutput)
        dumpMethod = getattr(rawOutput, "model_dump", None)
        if callable(dumpMethod):
            dumpedOutput: object = dumpMethod()
            if isinstance(dumpedOutput, dict):
                return JudgeDraft.model_validate(dumpedOutput)
        return AgentRunError(message="judge returned an unknown shape", agent="judge")
    except Exception as caughtError:
        return AgentRunError(
            message=f"judge parse failed: {type(caughtError).__name__}: {caughtError}",
            agent="judge",
        )


async def runJudgeAgent(
    *,
    generatedComments: list[CodeCommentDraft],
    goldenComments: list[GoldenComment],
    llm: LLMCtx,
    systemPrompt: str = JUDGE_SYSTEM_PROMPT,
) -> JudgeResult | AgentRunError:
    """Judge generated comments against golden comments.

    Returns the structured verdict with confidence plus match counts,
    or an AgentRunError value on expected failure. Never raises for
    business failures.
    """
    model = createLLMModel(llm)
    if isinstance(model, LLMConfigError):
        return AgentRunError(message=f"bad judge model config: {model}", agent="judge")
    payload = buildJudgePayload(generatedComments, goldenComments)
    try:
        structured = model.with_structured_output(JudgeDraft)
        rawOutput: object = await structured.ainvoke(
            [
                SystemMessage(content=systemPrompt),
                HumanMessage(content=json.dumps(payload, indent=2)[:60000]),
            ]
        )
    except Exception as caughtError:
        return AgentRunError(
            message=f"judge call failed: {type(caughtError).__name__}: {caughtError}",
            agent="judge",
            retryable=True,
        )
    draft = coerceJudgeDraft(rawOutput)
    if isinstance(draft, AgentRunError):
        return draft
    return buildJudgeResult(
        draft,
        goldenTotal=len(goldenComments),
        generatedTotal=len(generatedComments),
        judgeModel=llm.model,
    )


__all__ = [
    "JUDGE_SYSTEM_PROMPT",
    "JudgeDraft",
    "JudgeFalsePositive",
    "JudgeMatch",
    "JudgeResult",
    "buildJudgePayload",
    "buildJudgeResult",
    "coerceJudgeDraft",
    "runJudgeAgent",
]
