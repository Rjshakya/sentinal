"""Repair-and-publish step: the deepagent harness that publishes a saved
review to GitHub with LLM-driven anchor repair.

The saved summary + comments failed to post to GitHub once (validation
error / anchor mismatch). This step runs the **deepagent harness** —
:func:`deepagents.create_deep_agent` over the run's chat model with the
sandbox as backend and one tool:

- :func:`buildPublishTool` — the ``publish_to_github`` tool: takes the
  corrected :class:`CommentRow` list (each row carries its DB id), and
  posts the full review — the saved summary + verdict plus the comment
  rows — as one atomic review via the installation client. Because the
  review POST is atomic, a successful call posts exactly the rows it
  was given; the tool records them (plus the review id) in a closure
  holder the host reads after the run. On failure it returns GitHub's
  validation details verbatim so the agent can fix the reported anchors
  and retry.
- :func:`repairAndPublish` — the worker: builds the model, reconnects
  the sandbox, compiles the harness (story prompt + tool + the shared
  middleware stack with a 3-call tool cap), runs it, and partitions the
  original rows into posted / left by the holder's posted ids.
- :func:`repairAndPublishToGithub` — the DBOS step edge: runs the
  worker and raises for the error cases.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from dbos import DBOS
from deepagents import create_deep_agent
from githubkit.exception import RequestFailed
from githubkit_schemas.v2026_03_10.types import (
    ReposOwnerRepoPullsPullNumberReviewsPostBodyPropCommentsItemsType,
    ReposOwnerRepoPullsPullNumberReviewsPostBodyType,
)
from langchain_core.messages import HumanMessage
from langchain_core.tools import BaseTool, tool
from pydantic import BaseModel, Field

from app.services.agent.middleware import buildAgentMiddleware
from app.services.github.pr.service import createPRCtx
from app.services.github.pr.types import PRCommentDraft
from app.services.llm.errors import LLMConfigError
from app.services.llm.service import createLLMModel
from app.services.sandbox.types import SandboxCtx
from app.workflows.repair_and_publish.errors import (
    PublishError,
    RepairPublishStepFailure,
    TransientRepairPublishStepFailure,
    shouldRetry,
)
from app.workflows.repair_and_publish.helpers import (
    buildStoryPrompt,
    buildUserPrompt,
    toGithubComments,
)
from app.workflows.repair_and_publish.types import (
    CommentRow,
    PublishedReview,
    RepairAndPublishWorkflowCtx,
    UnpublishedReview,
)
from app.workflows.review.errors import (
    SandboxConnectError,
    isLlmRetryError,
)
from app.workflows.review.steps._helpers import connectSandbox

log = logging.getLogger(__name__)

_MAX_TOOL_CALLS = 200
"""Hard cap on ``publish_to_github`` tool calls per run (middleware)."""
_MAX_MODEL_CALLS = 200
"""Hard cap on model calls per run (middleware)."""


class PublishCommentsInput(BaseModel):
    """Tool arguments: the full corrected comment-row list."""

    comments: list[CommentRow] = Field(
        default_factory=list,
        description=(
            "The review's inline comments with any anchor corrections "
            "applied (fileName / side / fromLine / toLine). Every "
            "comment carries its DB id — keep the ids unchanged. The "
            "bodies must be exactly as given."
        ),
    )


def _toCommentItem(
    draft: PRCommentDraft,
) -> ReposOwnerRepoPullsPullNumberReviewsPostBodyPropCommentsItemsType:
    """Convert one GitHub comment draft to the body item."""
    return {
        "path": draft.fileName,
        "line": draft.line,
        "side": draft.side,
        "body": draft.body,
    }


def _statusCode(exc: Exception) -> int | None:
    """Return the HTTP status when the exception carries one."""
    if isinstance(exc, RequestFailed):
        return exc.response.status_code
    return None


def _extractValidationBody(exc: Exception) -> dict[str, Any] | None:
    """Best-effort GitHub validation body from a githubkit failure.

    ``ValidationErrorSimple`` carries ``message`` plus a field-level
    ``errors`` list (e.g. the offending ``comments[N].path``) — exactly
    the detail the repair agent needs to fix anchors.
    """
    if isinstance(exc, RequestFailed):
        try:
            body = exc.response.json()
        except Exception:
            return None
        return body if isinstance(body, dict) else None
    return None


def buildPublishTool(
    ctx: UnpublishedReview,
    holder: list[dict[str, Any]],
) -> BaseTool:
    """Build the ``publish_to_github`` tool for a run's ctx.

    The tool closes over the run's data and posts the full review — the
    saved summary + verdict and the corrected comment rows — in one
    atomic ``POST /pulls/{n}/reviews``; only the comment rows come from
    the agent's call. On success the posted review id, the attempt
    count, and the posted row ids are appended to ``holder`` — the
    single source of truth the host reads after the harness run. A
    repeat call after success returns the same success result without
    posting again.
    """

    @tool(
        "publish_to_github",
        args_schema=PublishCommentsInput,
        response_format="content",
    )
    async def publishToGithub(comments: list[CommentRow]) -> str:
        """Publish the saved review to GitHub as one atomic review: the summary + verdict and the corrected inline comments.

        Returns JSON: {"success": true, "github_review_id": <id>} on
        acceptance, or {"success": false, "status": <code>, "message":
        "...", "errors": {...}} with GitHub's validation details. On
        failure, fix the reported anchors and call again (at most 3
        calls).
        """
        attempts = len(holder) + 1
        if holder:
            posted_id = holder[0].get("github_review_id")
            if isinstance(posted_id, int):
                return json.dumps({"success": True, "github_review_id": posted_id})

        prCtx = createPRCtx(
            userId=ctx.userId,
            installationId=ctx.installationId,
            owner=ctx.repoOwner,
            repo=ctx.repoName,
            prNumber=ctx.prNumber,
            commitId=ctx.commitId,
        )
        body: ReposOwnerRepoPullsPullNumberReviewsPostBodyType = {
            "commit_id": ctx.commitId,
            "event": ctx.verdict,
            "body": ctx.summary,
            "comments": [_toCommentItem(draft) for draft in toGithubComments(comments)],
        }
        try:
            resp = await prCtx.client.rest.pulls.async_create_review(
                owner=ctx.repoOwner,
                repo=ctx.repoName,
                pull_number=ctx.prNumber,
                data=body,
            )
        except Exception as exc:
            return json.dumps(
                {
                    "success": False,
                    "status": _statusCode(exc),
                    "message": str(exc),
                    "errors": _extractValidationBody(exc),
                }
            )

        parsed = resp.parsed_data
        reviewId = parsed.id if parsed is not None else None
        if isinstance(reviewId, int) and not holder:
            holder.append(
                {
                    "github_review_id": reviewId,
                    "attempts": attempts,
                    "posted_comments": comments,
                }
            )
        return json.dumps({"success": True, "github_review_id": reviewId})

    return publishToGithub


async def repairAndPublish(
    ctx: RepairAndPublishWorkflowCtx,
    unpublished: UnpublishedReview,
    sandboxCtx: SandboxCtx,
    diffDir: str,
) -> PublishedReview | None | PublishError:
    """Run the repair agent (deepagent harness) for one publish attempt.

    Returns:
        :class:`PublishedReview` once GitHub accepts the review
        (summary + verdict + comments) — the holder's posted row ids
        partition the original rows into ``postedComments`` /
        ``leftComments``;
        ``None`` when the agent finished without publishing anything;
        a :class:`PublishError` value for model-build / sandbox /
        LLM failures. Never raises.
    """
    chat = createLLMModel(ctx.llmCtx)
    if isinstance(chat, LLMConfigError):
        return PublishError(
            message=f"failed to build repair model: {chat}",
            reviewId=unpublished.reviewId,
            repoId=unpublished.repoId,
            prNumber=unpublished.prNumber,
        )

    sandbox = await connectSandbox(sandboxCtx)
    if isinstance(sandbox, SandboxConnectError):
        return PublishError(
            message=sandbox.message,
            reviewId=unpublished.reviewId,
            repoId=unpublished.repoId,
            prNumber=unpublished.prNumber,
            retryable=True,
        )

    holder: list[dict[str, Any]] = []
    publish_tool = buildPublishTool(unpublished, holder)
    try:
        agent = create_deep_agent(
            model=chat,
            system_prompt=buildStoryPrompt(unpublished, diffDir),
            backend=sandbox,
            tools=[publish_tool],
            middleware=buildAgentMiddleware(
                modelCallRunLimit=_MAX_MODEL_CALLS,
                toolCallRunLimit=_MAX_TOOL_CALLS,
            ),
        )
    except Exception as exc:
        return PublishError(
            message=f"failed to build repair agent: {type(exc).__name__}: {exc}",
            reviewId=unpublished.reviewId,
            repoId=unpublished.repoId,
            prNumber=unpublished.prNumber,
        )

    try:
        await agent.ainvoke(
            {"messages": [HumanMessage(content=buildUserPrompt(unpublished, diffDir))]}
        )
    except Exception as exc:
        return PublishError(
            message=f"repair agent run failed: {type(exc).__name__}: {exc}",
            reviewId=unpublished.reviewId,
            repoId=unpublished.repoId,
            prNumber=unpublished.prNumber,
            retryable=isLlmRetryError(exc),
        )

    if not holder:
        return None
    posted = holder[0]
    reviewId = posted.get("github_review_id")
    if reviewId is None:
        return None

    postedComments: list[CommentRow] | None = posted.get("posted_comments")

    if postedComments is None:
        return None

    postedIdSet = set(row.commentId for row in postedComments)
    leftComments = [
        row for row in unpublished.comments if row.commentId not in postedIdSet
    ]
    return PublishedReview(
        githubReviewId=reviewId,
        postedComments=postedComments,
        leftComments=leftComments,
        attempts=int(posted.get("attempts", 0)),
    )


@DBOS.step(
    retries_allowed=True,
    max_attempts=2,
    should_retry=shouldRetry,
    backoff_rate=2,
)
async def repairAndPublishToGithub(
    *,
    ctx: RepairAndPublishWorkflowCtx,
    unpublished: UnpublishedReview,
    sandboxCtx: SandboxCtx,
    diffDir: str,
) -> PublishedReview | None:
    """Durable step: repair and publish the saved review to GitHub.

    Runs the deepagent harness. The posted / left partition comes from
    the successful tool call — no per-comment fetch is needed because
    the review POST is atomic.

    Raises:
        TransientRepairPublishStepFailure: transient LLM / sandbox
            failure — DBOS retries the step.
        RepairPublishStepFailure: final model-build failure.
    Returns:
        :class:`PublishedReview` with the posted / left partitions, or
        ``None`` when the agent finished without publishing anything.
    """
    result = await repairAndPublish(ctx, unpublished, sandboxCtx, diffDir)
    if isinstance(result, PublishError):
        if result.retryable:
            raise TransientRepairPublishStepFailure(result)
        raise RepairPublishStepFailure(result)
    if result is None:
        log.warning(
            "repair_and_publish: agent published nothing: pr_number=%s review_id=%s",
            unpublished.prNumber,
            unpublished.reviewId,
        )
        return None

    log.info(
        "repair_and_publish_step: ok pr_number=%s github_review_id=%s "
        "posted=%d left=%d attempts=%d",
        unpublished.prNumber,
        result.githubReviewId,
        len(result.postedComments),
        len(result.leftComments),
        result.attempts,
    )
    return result


__all__ = [
    "PublishCommentsInput",
    "buildPublishTool",
    "repairAndPublish",
    "repairAndPublishToGithub",
]
