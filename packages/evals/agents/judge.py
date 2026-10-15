"""Judge agent: review plus gold in, structured verdict out."""

from __future__ import annotations

import json
from typing import Annotated, Literal

from app.services.llm.errors import LLMConfigError
from app.services.llm.service import createLLMModel
from app.services.llm.types import LLMCtx
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, ConfigDict, Field

from agents.base import AgentRunError, ReviewOutput
from datasets.types import GoldOutput

JUDGE_SYSTEM_PROMPT = """\
You are the evaluator for an AI code-review agent. You judge a predicted review
against the ground-truth findings (gold) the dataset authors curated.

You receive two inputs:
1. "review" -- the agent's verdict, summary, and predicted inline comments.
2. "gold" -- the ground-truth findings a human expert expects (verdict + bugs).

For EACH predicted comment (comment_idx is its index in the review comments list):
- verdict: "real_bug" = a concrete issue that should be fixed (trace a failure:
  crash, wrong result, data loss, security hole); "nitpick" = valid but minor
  (style, naming, low-impact); "false_positive" = not a real issue (wrong claim,
  hallucinated line, generic advice, duplicate of another comment).
- matched_gold_idx: the gold bug's index when this comment addresses the SAME
  issue -- match by same file + overlapping/adjacent line range + same substance
  (line numbers may differ by a few lines). None when nothing matches.
- severity_matches: for matched findings only, whether the predicted severity
  (P1_CRITICAL/P2_WARNING/P3_NITPICK) equals the gold severity. None when unmatched.
- reason: one short paragraph justifying verdict + match.

Then judge the summary:
- faithful: every claim in the summary reflects a real change in the PR.
- concise: readable quickly; no line-by-line narration or filler.
- missing_key_risks: real risks the gold bugs surface that the summary missed.

Finally set verdict_matches_gold: does the review's overall verdict
(APPROVE/COMMENT/REQUEST_CHANGES) equal the gold verdict?

Rules:
- Be strict but fair. A false positive is worse than a missed nit.
- Never invent gold matches: only match when the substance is the same issue.
- Do not reward or punish comment count; judge substance.
"""


class JudgeCommentVerdict(BaseModel):
    """The judge's verdict on one predicted comment."""

    model_config = ConfigDict(frozen=True)

    comment_idx: int = Field(ge=0)
    verdict: Literal["real_bug", "nitpick", "false_positive"]
    matched_gold_idx: int | None = Field(default=None, ge=0)
    severity_matches: bool | None = Field(default=None)
    reason: str = Field(default="")


class JudgeSummaryVerdict(BaseModel):
    """The judge's verdict on the review summary."""

    model_config = ConfigDict(frozen=True)

    faithful: bool
    concise: bool
    missing_key_risks: Annotated[list[str], Field(default_factory=list)]


class JudgeVerdict(BaseModel):
    """The full structured judgement for one review run."""

    model_config = ConfigDict(frozen=True)

    verdict_matches_gold: bool
    comments: Annotated[list[JudgeCommentVerdict], Field(default_factory=list)]
    summary: JudgeSummaryVerdict
    overall_reasoning: str = Field(default="")


async def runJudgeAgent(
    *,
    review: ReviewOutput,
    gold: GoldOutput,
    llm: LLMCtx,
    systemPrompt: str = JUDGE_SYSTEM_PROMPT,
) -> JudgeVerdict | AgentRunError:
    """Judge one review run against its gold output.

    Returns the structured verdict, or an :class:`AgentRunError` value
    on expected failure. Never raises for business failures.
    """
    model = createLLMModel(llm)
    if isinstance(model, LLMConfigError):
        return AgentRunError(
            message=f"bad judge model config: {model}", agent="judge"
        )
    payload = {
        "review": {
            "verdict": review.verdict,
            "summary": review.summary,
            "comments": [
                {"index": i, **c.model_dump(mode="json")}
                for i, c in enumerate(review.comments)
            ],
        },
        "gold": {
            "verdict": gold.verdict,
            "bugs": [
                {"index": i, **b.model_dump(mode="json")}
                for i, b in enumerate(gold.bugs)
            ],
        },
    }
    try:
        structured = model.with_structured_output(JudgeVerdict)
        raw: object = await structured.ainvoke(
            [
                SystemMessage(content=systemPrompt),
                HumanMessage(content=json.dumps(payload, indent=2)[:60000]),
            ]
        )
    except Exception as exc:
        return AgentRunError(
            message=f"judge call failed: {type(exc).__name__}: {exc}",
            agent="judge",
            retryable=True,
        )
    try:
        if isinstance(raw, JudgeVerdict):
            return raw
        if isinstance(raw, dict):
            return JudgeVerdict.model_validate(raw)
        dump = getattr(raw, "model_dump", None)
        if callable(dump):
            dumped: object = dump()
            if isinstance(dumped, dict):
                return JudgeVerdict.model_validate(dumped)
        return AgentRunError(
            message="judge returned an unknown shape", agent="judge"
        )
    except Exception as exc:
        return AgentRunError(
            message=f"judge parse failed: {type(exc).__name__}: {exc}",
            agent="judge",
        )


__all__ = [
    "JUDGE_SYSTEM_PROMPT",
    "JudgeCommentVerdict",
    "JudgeSummaryVerdict",
    "JudgeVerdict",
    "runJudgeAgent",
]
