"""Unit tests for the review system prompts.

The research agents (summarizer / comments) are prompt-driven and
produce free-form text — they must NOT carry a JSON output contract.
The structured payloads are produced by the extractor steps in
:mod:`app.services.review.steps.extract_result`, whose prompts embed
the auto-generated JSON schema of their response models, so the
extractor's text-JSON fallback still sees the exact shape the
pipeline validates against.
"""

from __future__ import annotations

import json

import pytest

from app.services.agent.models import ReviewComments, SummaryResult
from app.services.agent.prompts import (
    PR_SUMMARY_SYSTEM_PROMPT,
    REVIEW_COMMENTS_SYSTEM_PROMPT,
    _render_schema,
)
from app.services.review.steps.extract_result import (
    COMMENTS_EXTRACTION_SYSTEM_PROMPT,
    SUMMARY_EXTRACTION_SYSTEM_PROMPT,
)


def _extract_tail_schema(prompt: str) -> dict:
    """Parse the JSON block that follows the OUTPUT SCHEMA marker."""
    marker = prompt.rfind("OUTPUT SCHEMA")
    assert marker != -1, "prompt has no OUTPUT SCHEMA marker"
    start = prompt.index("{", marker)
    return json.loads(prompt[start:])


def test_agent_prompts_carry_no_json_contract() -> None:
    """Research agents are free-form: no schema tail on either prompt."""
    for prompt in (PR_SUMMARY_SYSTEM_PROMPT, REVIEW_COMMENTS_SYSTEM_PROMPT):
        assert "OUTPUT SCHEMA" not in prompt
        assert "```json" not in prompt


def test_summary_extractor_prompt_ends_with_summaryresult_schema() -> None:
    schema = _extract_tail_schema(SUMMARY_EXTRACTION_SYSTEM_PROMPT)

    assert schema == json.loads(_render_schema(SummaryResult))
    assert schema["properties"]["summary"]["type"] == "string"
    assert schema["required"] == ["summary"]


def test_comments_extractor_prompt_ends_with_reviewcomments_schema() -> None:
    schema = _extract_tail_schema(COMMENTS_EXTRACTION_SYSTEM_PROMPT)

    assert schema == json.loads(_render_schema(ReviewComments))

    list_field = schema["properties"]["List"]
    assert list_field["type"] == "array"
    assert list_field["items"]["$ref"] == "#/$defs/CodeCommentDraft"

    draft = schema["$defs"]["CodeCommentDraft"]
    properties = draft["properties"]
    assert properties["severity"]["enum"] == [
        "P1_CRITICAL",
        "P2_WARNING",
        "P3_NITPICK",
    ]
    assert properties["side"]["enum"] == ["RIGHT", "LEFT"]
    assert properties["from_line"]["type"] == "integer"
    assert properties["to_line"]["type"] == "integer"
    assert draft["required"] == [
        "file_name",
        "comment",
        "severity",
        "from_line",
        "to_line",
    ]


@pytest.mark.parametrize(
    ("prompt", "model_cls"),
    [
        (SUMMARY_EXTRACTION_SYSTEM_PROMPT, SummaryResult),
        (COMMENTS_EXTRACTION_SYSTEM_PROMPT, ReviewComments),
    ],
)
def test_schema_is_last_block_of_each_extractor_prompt(
    prompt: str,
    model_cls: type[SummaryResult | ReviewComments],
) -> None:
    schema = _extract_tail_schema(prompt)

    assert prompt.rstrip().endswith(json.dumps(schema, indent=2))
    assert "OUTPUT SCHEMA" in prompt[: prompt.rfind("{")]