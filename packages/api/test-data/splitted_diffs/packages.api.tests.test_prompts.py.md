### packages/api/tests/test_prompts.py

```diff

deleted file mode 100644
index 1407231..0000000
--- a/packages/api/tests/test_prompts.py
+++ /dev/null
@@ -1,81 +0,0 @@
    2       -"""Unit tests for the review-agent system prompts.
    3       -
    4       -Each prompt's tail embeds the auto-generated JSON schema of its
    5       -response model, so text-JSON providers (which drop ``response_format``)
    6       -still see the exact output shape the pipeline validates against.
    7       -"""
    8       -
    9       -from __future__ import annotations
   10       -
   11       -import json
   12       -
   13       -import pytest
   14       -
   15       -from app.services.agent.models import ReviewComments, SummaryResult
   16       -from app.services.agent.prompts import (
   17       -    PR_SUMMARY_SYSTEM_PROMPT,
   18       -    REVIEW_COMMENTS_SYSTEM_PROMPT,
   19       -    _render_schema,
   20       -)
   21       -
   22       -
   23       -def _extract_tail_schema(prompt: str) -> dict:
   24       -    """Parse the JSON block that follows the OUTPUT SCHEMA marker."""
   25       -    marker = prompt.rfind("OUTPUT SCHEMA")
   26       -    assert marker != -1, "prompt has no OUTPUT SCHEMA marker"
   27       -    start = prompt.index("{", marker)
   28       -    return json.loads(prompt[start:])
   29       -
   30       -
   31       -def test_summary_prompt_ends_with_summaryresult_schema() -> None:
   32       -    schema = _extract_tail_schema(PR_SUMMARY_SYSTEM_PROMPT)
   33       -
   34       -    assert schema == json.loads(_render_schema(SummaryResult))
   35       -    assert schema["properties"]["summary"]["type"] == "string"
   36       -    assert schema["required"] == ["summary"]
   37       -
   38       -
   39       -def test_comments_prompt_ends_with_reviewcomments_schema() -> None:
   40       -    schema = _extract_tail_schema(REVIEW_COMMENTS_SYSTEM_PROMPT)
   41       -
   42       -    assert schema == json.loads(_render_schema(ReviewComments))
   43       -
   44       -    list_field = schema["properties"]["List"]
   45       -    assert list_field["type"] == "array"
   46       -    assert list_field["items"]["$ref"] == "#/$defs/CodeCommentDraft"
   47       -
   48       -    draft = schema["$defs"]["CodeCommentDraft"]
   49       -    properties = draft["properties"]
   50       -    assert properties["severity"]["enum"] == [
   51       -        "P1_CRITICAL",
   52       -        "P2_WARNING",
   53       -        "P3_NITPICK",
   54       -    ]
   55       -    assert properties["side"]["enum"] == ["RIGHT", "LEFT"]
   56       -    assert properties["from_line"]["type"] == "integer"
   57       -    assert properties["to_line"]["type"] == "integer"
   58       -    assert draft["required"] == [
   59       -        "file_name",
   60       -        "comment",
   61       -        "severity",
   62       -        "from_line",
   63       -        "to_line",
   64       -    ]
   65       -
   66       -
   67       -@pytest.mark.parametrize(
   68       -    ("prompt", "model_cls"),
   69       -    [
   70       -        (PR_SUMMARY_SYSTEM_PROMPT, SummaryResult),
   71       -        (REVIEW_COMMENTS_SYSTEM_PROMPT, ReviewComments),
   72       -    ],
   73       -)
   74       -def test_schema_is_last_block_of_each_prompt(
   75       -    prompt: str,
   76       -    model_cls: type[SummaryResult | ReviewComments],
   77       -) -> None:
   78       -    schema = _extract_tail_schema(prompt)
   79       -
   80       -    assert prompt.rstrip().endswith(json.dumps(schema, indent=2))
   81       -    assert "OUTPUT SCHEMA" in prompt[: prompt.rfind("{")]
   82       -

```
