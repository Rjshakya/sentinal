"""Repair-phase steps: load unpublished review, run repair agent, save outcome.

Each step validates its input first, runs one operation via
``asyncio.run``, and returns ``model_dump(mode="json")``. Imports on top.
Fail-closed steps let exceptions propagate for SDK retry; the handler
marks the run FAILED when retries exhaust. The cloned-repo delete is
best-effort and never raises.
"""

from __future__ import annotations

import asyncio
import json
import logging
import shlex
from dataclasses import dataclass, field
from typing import Any

from aws_durable_execution_sdk_python import durable_step
from aws_durable_execution_sdk_python.types import StepContext
from deepagents import create_deep_agent
from githubkit.exception import RequestFailed
from langchain.agents.middleware import (
    ModelCallLimitMiddleware,
    ModelRetryMiddleware,
    ToolCallLimitMiddleware,
)
from langchain.agents.middleware.types import AgentMiddleware
from langchain_core.messages import HumanMessage
from langchain_core.tools import BaseTool, tool
from pydantic import BaseModel, ConfigDict, Field
from sqlmodel import col
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.db import async_session_maker
from app.models.code_comment import CodeComment
from app.models.review import Review
from app.models.review_summary import ReviewSummary
from app.repositories.code_comment import CodeCommentRepository
from app.repositories.installation import InstallationRepository
from app.repositories.repo import RepoRepository
from app.repositories.review import ReviewRepository
from app.repositories.review_summary import ReviewSummaryRepository
from app.services.github.pr.service import createPRCtx
from app.services.github.pr.types import PRCommentDraft
from app.services.llm.errors import LLMConfigError
from app.services.llm.service import createLLMModel
from app.services.llm.types import LLMCtx
from app.services.sandbox.types import SandboxCtx
from app.workflows.review_v2.errors import SandboxConnectError
from app.utils.branded import (
    CommitId,
    InstallationId,
    PRNumber,
    RepoId,
    RepoName,
    RepoOwner,
    ReviewRowId,
    UserId,
)
from app.utils.schema import CommentSeverityStr, CommentSideStr, ReviewVerdictStr
from app.workflows.durable.types import CommentRow, PublishedReview, UnpublishedReview
from app.workflows.review_v2.steps._helpers import (
    asAsyncSandbox,
    connectSandbox,
    getRepoPath,
)
from app.workflows.triggers.repair import triggerRepairAfterReview

log = logging.getLogger(__name__)

REPAIR_MAX_TOOL_CALLS = 3
REPAIR_MAX_MODEL_CALLS = 200


@durable_step
def loadUnpublishedReview(_ctx: StepContext, *, commitId: str) -> dict | None:
    """Load the publishable review for a commit, else None (nothing to do)."""

    async def run() -> dict | None:
        async with async_session_maker() as session:
            reviews = ReviewRepository(session=session)
            review = await reviews.find(
                col(Review.commit_id) == commitId,
                col(Review.github_review_id).is_(None),
                one=True,
            )
            if review is None:
                return None
            reviewId = ReviewRowId(review.id)

            summaries = ReviewSummaryRepository(session=session)
            summary = await summaries.find(
                col(ReviewSummary.review_id) == reviewId,
                col(ReviewSummary.github_review_id).is_(None),
                one=True,
            )
            if summary is None or summary.github_review_id is not None:
                return None

            comments_repo = CodeCommentRepository(session=session)
            comment_rows = await comments_repo.find(
                col(CodeComment.review_id) == reviewId,
                col(CodeComment.github_review_id).is_(None),
                order_by=col(CodeComment.created_at),
            )
            repo = await RepoRepository(session=session).get(review.repo_id)
            if repo is None:
                raise RuntimeError(f"no repo row for review {reviewId!r}")
            installation = await InstallationRepository(
                session=session
            ).find_by_user_and_login(
                review.user_id,
                repo.repo_owner,
                active_only=True,
            )
            if installation is None:
                raise RuntimeError(
                    f"no installation for user {review.user_id!r} / owner "
                    f"{repo.repo_owner!r}"
                )

            comments = [
                CommentRow(
                    commentId=row.id,
                    fileName=row.file_name,
                    fromLine=row.from_line,
                    toLine=row.to_line,
                    side=row.side.value,  # type: ignore[arg-type]
                    severity=row.severity.value,  # type: ignore[arg-type]
                    body=row.comment,
                    nodeType=row.node_type,
                )
                for row in comment_rows
            ]
            return UnpublishedReview(
                reviewId=ReviewRowId(review.id),
                userId=UserId(review.user_id),
                repoId=RepoId(review.repo_id),
                prNumber=PRNumber(review.pr_number),
                commitId=CommitId(review.commit_id),
                baseSha=review.base_sha,
                repoOwner=RepoOwner(repo.repo_owner),
                repoName=RepoName(repo.repo_name),
                installationId=InstallationId(installation.github_installation_id),
                summary=summary.summary,
                verdict=summary.verdict.value,  # type: ignore[arg-type]
                comments=comments,
            ).model_dump(mode="json")

    return asyncio.run(run())


def buildRepairMiddleware(
    *, modelCallRunLimit: int, toolCallRunLimit: int
) -> list[AgentMiddleware[Any, None, Any]]:
    """Build the repair agent's middleware stack (retry + call caps)."""
    return [
        ModelRetryMiddleware(
            max_retries=3,
            backoff_factor=2.0,
            initial_delay=1.0,
            on_failure="error",
        ),
        ModelCallLimitMiddleware(run_limit=modelCallRunLimit),
        ToolCallLimitMiddleware(run_limit=toolCallRunLimit),
    ]


def buildStoryPrompt(ctx: UnpublishedReview, diffDir: str) -> str:
    """Build the repair agent's system prompt (anchors only, content final)."""
    return (
        "You are the publish agent for a GitHub PR-review pipeline.\n"
        "\n"
        f"The review pipeline produced a summary (with a verdict) and a set of "
        f"inline comments for PR #{ctx.prNumber} at commit {ctx.commitId}, but "
        f"posting them to GitHub failed with a validation error — GitHub rejected "
        f"the review payload. Your job is to publish the saved review exactly as "
        f"produced, fixing ONLY the file_name or anchors GitHub rejected.\n"
        "\n"
        "Setup:\n"
        f"- The diff artefacts live at {diffDir}: overview.md and splitted_diffs/ "
        f'(one file per changed file, each with a `### <real file path>` header '
        f"followed by a fenced diff block showing that file's hunks with "
        f"LEFT/RIGHT gutter line numbers).\n"
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
        "diff block (RIGHT gutter = new-side line, LEFT gutter = old-side line).\n"
        "- If a finding cannot be re-anchored to the diff, drop that finding "
        "entirely — it will not be posted.\n"
        "- Publish with the publish_to_github tool, passing the full corrected "
        "comment list; the summary and verdict travel with the same call as one "
        "atomic review POST. If the tool returns an error, fix the reported "
        "comments and call the tool again (at most 3 calls).\n"
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
        "Saved review payload (content is final, fix only file_name or anchors):\n"
        f"{json.dumps(payload, indent=2)}\n"
    )


def toGithubComments(rows: list[CommentRow]) -> list[PRCommentDraft]:
    """Convert CommentRow items to GitHub comment items (drops bad lines)."""
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


@dataclass
class PublishOutcome:
    """Mutable holder for the publish tool's successful call."""

    github_review_id: int | None = None
    attempts: int = 0
    posted_comments: list[CommentRow] = field(default_factory=list)


class PublishCommentsInput(BaseModel):
    """Tool arguments: the full corrected comment-row list."""

    comments: list[CommentRow] = Field(default_factory=list)


def publishStatusCode(exc: Exception) -> int | None:
    if isinstance(exc, RequestFailed):
        return exc.response.status_code
    return None


def publishValidationBody(exc: Exception) -> dict | None:
    if isinstance(exc, RequestFailed):
        try:
            body = exc.response.json()
        except Exception:
            return None
        return body if isinstance(body, dict) else None
    return None


def buildPublishTool(ctx: UnpublishedReview, holder: PublishOutcome) -> BaseTool:
    """Build the publish_to_github tool: one atomic review POST per call."""

    @tool(
        "publish_to_github",
        args_schema=PublishCommentsInput,
        response_format="content",
    )
    async def publishToGithub(comments: list[CommentRow]) -> str:
        """Publish the saved review as one atomic GitHub review.

        Returns {"success": true, "github_review_id": <id>} on acceptance,
        or {"success": false, ...} with GitHub's validation details.
        """
        if holder.github_review_id is not None:
            return json.dumps(
                {"success": True, "github_review_id": holder.github_review_id}
            )
        holder.attempts += 1

        prCtx = createPRCtx(
            userId=ctx.userId,
            installationId=ctx.installationId,
            owner=ctx.repoOwner,
            repo=ctx.repoName,
            prNumber=ctx.prNumber,
            commitId=ctx.commitId,
        )
        try:
            resp = await prCtx.client.rest.pulls.async_create_review(
                owner=ctx.repoOwner,
                repo=ctx.repoName,
                pull_number=ctx.prNumber,
                data={
                    "commit_id": ctx.commitId,
                    "event": ctx.verdict,
                    "body": ctx.summary,
                    "comments": [
                        {
                            "path": draft.fileName,
                            "line": draft.line,
                            "side": draft.side,
                            "body": draft.body,
                        }
                        for draft in toGithubComments(comments)
                    ],
                },
            )
        except Exception as exc:
            return json.dumps(
                {
                    "success": False,
                    "status": publishStatusCode(exc),
                    "message": str(exc),
                    "errors": publishValidationBody(exc),
                }
            )

        parsed = resp.parsed_data
        reviewId = parsed.id if parsed is not None else None
        if not isinstance(reviewId, int):
            return json.dumps({"success": False, "message": "empty review payload"})
        holder.github_review_id = reviewId
        holder.posted_comments = list(comments)
        return json.dumps({"success": True, "github_review_id": reviewId})

    return publishToGithub


class RepairAgentInput(BaseModel):
    model_config = ConfigDict(frozen=True)

    llm: LLMCtx
    unpublished: UnpublishedReview
    sandbox: SandboxCtx
    diffDir: str


@durable_step
def runRepairAgent(_ctx: StepContext, *, input: dict) -> dict | None:
    """Run the repair agent; returns PublishedReview dump, else None."""

    async def run() -> PublishedReview | None:
        request = RepairAgentInput.model_validate(input)
        unpublished = request.unpublished

        chat = createLLMModel(request.llm)
        if isinstance(chat, LLMConfigError):
            raise RuntimeError(f"failed to build repair model: {chat}")

        sandbox = await connectSandbox(request.sandbox)
        if isinstance(sandbox, SandboxConnectError):
            raise RuntimeError(f"sandbox connect failed: {sandbox.message}")

        holder = PublishOutcome()
        agent = create_deep_agent(
            model=chat,
            system_prompt=buildStoryPrompt(unpublished, request.diffDir),
            backend=sandbox,
            tools=[buildPublishTool(unpublished, holder)],
            middleware=buildRepairMiddleware(
                modelCallRunLimit=REPAIR_MAX_MODEL_CALLS,
                toolCallRunLimit=REPAIR_MAX_TOOL_CALLS,
            ),
        )
        await agent.ainvoke(
            {
                "messages": [
                    HumanMessage(
                        content=buildUserPrompt(unpublished, request.diffDir)
                    )
                ]
            }
        )

        if holder.github_review_id is None:
            log.warning(
                "runRepairAgent: agent published nothing: pr=%s review=%s",
                unpublished.prNumber,
                unpublished.reviewId,
            )
            return None
        postedIds = {row.commentId for row in holder.posted_comments}
        return PublishedReview(
            githubReviewId=holder.github_review_id,
            postedComments=list(holder.posted_comments),
            leftComments=[
                row for row in unpublished.comments if row.commentId not in postedIds
            ],
            attempts=holder.attempts,
        )

    result = asyncio.run(run())
    if result is None:
        return None
    return result.model_dump(mode="json")


class SavePublishInput(BaseModel):
    model_config = ConfigDict(frozen=True)

    unpublished: UnpublishedReview
    published: PublishedReview


@durable_step
def savePublishOutcome(_ctx: StepContext, *, input: dict) -> dict:
    """Write posted ids onto review/summary/comments; delete left rows."""

    async def run() -> None:
        request = SavePublishInput.model_validate(input)
        unpublished = request.unpublished
        published = request.published
        githubId = str(published.githubReviewId)
        async with async_session_maker() as session:
            reviews = ReviewRepository(session=session)
            review = await reviews.get(unpublished.reviewId)
            if review is not None:
                review.github_review_id = githubId
                if published.postedComments:
                    review.comment_count = len(published.postedComments)
                await reviews.add(review)

            summaries = ReviewSummaryRepository(session=session)
            summary = await summaries.find_by_review_id(unpublished.reviewId)
            if summary is not None:
                summary.github_review_id = githubId
                await summaries.add(summary)

            comments = CodeCommentRepository(session=session)
            if published.postedComments:
                rows = await comments.find_by_ids(
                    [row.commentId for row in published.postedComments]
                )
                for row in rows:
                    row.github_review_id = githubId
                    await comments.add(row)
            if published.leftComments:
                await comments.delete(
                    col(CodeComment.id).in_(
                        [row.commentId for row in published.leftComments]
                    )
                )
            await session.commit()

    asyncio.run(run())
    return {}


class DeleteRepoInput(BaseModel):
    model_config = ConfigDict(frozen=True)

    sandbox: SandboxCtx
    repoName: str


@durable_step
def deleteClonedRepo(_ctx: StepContext, *, input: dict) -> dict:
    """Remove the cloned repo from the sandbox (best-effort, never raises)."""

    async def run() -> None:
        request = DeleteRepoInput.model_validate(input)
        sandbox = await connectSandbox(request.sandbox)
        if isinstance(sandbox, SandboxConnectError):
            log.warning(
                "deleteClonedRepo: reconnect failed (continuing): %s",
                sandbox.message,
            )
            return
        backend = asAsyncSandbox(sandbox)
        try:
            result = await backend.aexecute(
                f"rm -rf {shlex.quote(getRepoPath(request.repoName))}",
                timeout=60,
            )
        except Exception as exc:
            log.warning("deleteClonedRepo: rm failed (continuing): %s", exc)
            return
        if result.exit_code != 0:
            log.warning(
                "deleteClonedRepo: rm exited %s (continuing)",
                result.exit_code,
            )

    asyncio.run(run())
    return {}


class DispatchRepairInput(BaseModel):
    model_config = ConfigDict(frozen=True)

    prNumber: int
    commitId: str
    delivery: str


@durable_step
def dispatchRepairFollowUp(_ctx: StepContext, *, input: dict) -> bool:
    """Invoke the repair durable best-effort; False when invoke failed."""

    async def run() -> bool:
        request = DispatchRepairInput.model_validate(input)
        return await triggerRepairAfterReview(
            prNumber=request.prNumber,
            commitId=request.commitId,
            delivery=request.delivery,
        )

    return asyncio.run(run())


__all__ = [
    "PublishCommentsInput",
    "PublishOutcome",
    "buildPublishTool",
    "buildRepairMiddleware",
    "buildStoryPrompt",
    "buildUserPrompt",
    "deleteClonedRepo",
    "dispatchRepairFollowUp",
    "loadUnpublishedReview",
    "publishStatusCode",
    "publishValidationBody",
    "runRepairAgent",
    "savePublishOutcome",
    "toGithubComments",
]
