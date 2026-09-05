"""Pure helpers for the repair-and-publish workflow.

- :func:`buildStoryPrompt` / :func:`buildUserPrompt` — the repair
  agent's system + user messages: the saved review is final, only
  anchors may change, and the diff artefacts (``overview.md`` +
  ``splitted_diffs/`` chunks with gutter line numbers) are the ground
  truth for re-anchoring.
- :func:`toGithubComments` — :class:`CommentRow` → GitHub comment-item
  conversion (rows carry their ids through the agent loop; the drafts
  built here are what gets sent to the API), dropping ``fromLine < 1``
  / ``toLine < 1`` rows as final defence-in-depth.
"""

from __future__ import annotations

import json
from uuid import uuid4

from dbos import DBOS, SetWorkflowID
from pydantic import BaseModel

from app.services.github.pr.types import PRCommentDraft
from app.workflows.repair_and_publish.types import CommentRow, UnpublishedReview


def createRepairAndPublishWorkflowId(*, prNumber: int, commitId: str):

    id = str(uuid4())
    return f"repair:{prNumber}:{commitId}:{id[:7]}:publish"


def buildStoryPrompt(ctx: UnpublishedReview, diffDir: str) -> str:
    """Build the repair agent's system prompt.

    The saved review is final — the agent may only correct anchors so
    GitHub accepts the payload, and may drop findings that cannot be
    re-anchored. Publishing happens through the ``publish_to_github``
    tool, whose error details drive the repair loop.
    """
    return (
        "You are the publish agent for a GitHub PR-review pipeline.\n"
        f"\n"
        f"The review pipeline produced a summary (with a verdict) and a set of "
        f"inline comments for PR #{ctx.prNumber} at commit {ctx.commitId}, but "
        f"posting them to GitHub failed with a validation error — GitHub rejected "
        f"the review payload. Your job is to publish the saved review exactly as "
        f"produced, fixing ONLY the file_name or anchors GitHub rejected.\n"
        f"\n"
        f"Setup:\n"
        f"- The diff artefacts live at {diffDir}: overview.md and splitted_diffs/ "
        f'(one file per changed file, named <path with "/"→".">.md, each with a '
        f"`### <real file path>` header followed by a fenced ```diff block showing "
        f"that file's hunks with LEFT/RIGHT gutter line numbers).\n"
        "- Read overview.md first, then pull the chunks for the files you need to "
        "re-anchor.\n"
        "\n"
        "Rules:\n"
        "- The summary, the verdict, and every comment BODY are final. NEVER "
        "change, rewrite, paraphrase, truncate, or drop any text content.\n"
        "- Every comment carries its DB id — pass the ids back unchanged; they "
        "are how the pipeline tracks what was posted.\n"
        "- You may ONLY correct each comment's file_name, side, from_line and "
        "to_line so the comment anchors to a gutter-visible line in that file's "
        "diff block (RIGHT gutter = new-side line, LEFT gutter = old-side line; "
        "context lines have both, additions only RIGHT, deletions only LEFT).\n"
        "- If a finding cannot be re-anchored to the diff (e.g. its file is not "
        "in the chunks at all), drop that finding entirely — it will not be "
        "posted.\n"
        "- Publish with the publish_to_github tool, passing the full corrected "
        "comment list; the summary and verdict travel with the same call as one "
        "atomic review POST. If the tool returns an error, read the GitHub "
        "validation details, fix the reported comments, and call the tool again."
        "No need of reasoning and brain stroming on diff , most probably the validation error will"
        "be of file name or anchors , so just be focused on that ."
        "Each comment have a comment id , ignore , because it was from local db not from github"
        "Do not publish repeatedly same comments , make sure to idempontent"
        "Do it in most optimal, efficiently and fast. way (you do not have unlimited access to tools , so plan accordingly)\n"
    )


def buildUserPrompt(ctx: UnpublishedReview, diffDir: str) -> str:
    """Build the repair agent's user message: the saved payload verbatim."""
    payload = {
        "comments": [row.model_dump() for row in ctx.comments],
        "summary": ctx.summary,
        "verdict": ctx.verdict,
    }
    return (
        f"PR #{ctx.prNumber} — commit {ctx.commitId}\n"
        f"\n"
        f"Diff dir: {diffDir}\n"
        f"\n"
        "Saved review payload (produced by the pipeline; content is final, "
        "fix only the file_name or anchors:\n"
        f"{json.dumps(payload, indent=2)}\n"
    )


def toGithubComments(rows: list[CommentRow]) -> list[PRCommentDraft]:
    """Convert :class:`CommentRow` items to GitHub comment items.

    Drops rows with invalid line numbers (``fromLine < 1`` or
    ``toLine < 1``) because GitHub review comments require 1-based
    line numbers.
    """
    github_comments: list[PRCommentDraft] = []
    for row in rows:
        if row.fromLine < 1 or row.toLine < 1:
            continue
        github_comments.append(
            PRCommentDraft(
                fileName=row.fileName,
                line=row.fromLine,
                side=row.side,
                body=row.body,
            )
        )
    return github_comments


__all__ = [
    "buildStoryPrompt",
    "buildUserPrompt",
    "toGithubComments",
]
