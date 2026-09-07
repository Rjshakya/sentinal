"""Run the structured-output judge over the review result + gold dataset.

The judge compares the rendered review output (``result.md``) against
the gold dataset (``output.json``). No diff is materialised: the eval
runner POSTs the dataset input to ``POST /api/review`` and shapes the
response onto a ``ReviewOutput`` via
:meth:`agents.review.type.ReviewOutput.from_api_response` before calling
this module.
"""

from __future__ import annotations

import json

from langchain_core.messages import HumanMessage, SystemMessage

from agents.judge.llm import build_model
from agents.judge.prompt import JUDGE_SYSTEM_PROMPT
from agents.judge.type import JudgeInput, JudgeVerdict
from agents.review.type import parse_markdown


async def run(input: JudgeInput) -> JudgeVerdict:
    """Judge one review run: parse result.md, call the structured judge model."""
    review = parse_markdown(input.result_md)

    payload = {
        "review": {
            "verdict": review.verdict,
            "summary": review.summary,
            "comments": [
                {"index": i, **comment.model_dump()}
                for i, comment in enumerate(review.comments)
            ],
        },
        "gold": {
            "verdict": input.gold.verdict,
            "bugs": [
                {"index": i, **bug.model_dump()}
                for i, bug in enumerate(input.gold.bugs)
            ],
        },
    }

    model = build_model()
    structured = model.with_structured_output(JudgeVerdict)
    response = await structured.ainvoke(
        [
            SystemMessage(content=JUDGE_SYSTEM_PROMPT),
            HumanMessage(content=json.dumps(payload, indent=2)),
        ]
    )
    return JudgeVerdict.model_validate(response)


__all__ = ["run"]
