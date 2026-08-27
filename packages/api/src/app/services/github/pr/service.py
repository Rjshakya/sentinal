"""PR sub-service: pull-request events against the GitHub API.

Entry points (camelCase, matching the package convention):

- :func:`createPRCtx` — ctx factory: mints the installation client
  and assembles the ctx (the I/O boundary).
- :func:`getPrState` — PR snapshot via ``GET /pulls/{number}``.
- :func:`addReaction` — reaction on an issue comment
  (``POST /issues/comments/{id}/reactions``).
- :func:`postReview` — submit a review with inline comments
  (``POST /pulls/{number}/reviews``). GitHub API only — no DB writes.
- :func:`postComment` — issue comment on the PR
  (``POST /issues/{number}/comments``).

Error contract: **no function raises.** Expected failures are returned
as :class:`GitHubPRError` values (carrying the HTTP status when the
exception exposes one); callers discriminate with ``isinstance``.
GitHub API calls use the client carried on the ctx, minted by
:func:`createPRCtx` at the edge.
"""

from __future__ import annotations

from githubkit.exception import RequestFailed
from githubkit_schemas.v2026_03_10.models import (
    IssueComment,
    PullRequest,
    PullRequestReview,
)
from githubkit_schemas.v2026_03_10.types import (
    ReposOwnerRepoIssuesCommentsCommentIdReactionsPostBodyType,
    ReposOwnerRepoIssuesIssueNumberCommentsPostBodyType,
    ReposOwnerRepoPullsPullNumberReviewsPostBodyPropCommentsItemsType,
    ReposOwnerRepoPullsPullNumberReviewsPostBodyType,
)

from app.services.github.client import getAuthenticatedGitHubClient
from app.services.github.pr.errors import GitHubPRError
from app.services.github.pr.types import (
    PRCommentDraft,
    PRCtx,
    PRReviewDraft,
    PRState,
    ReactionContent,
)
from app.utils.branded import (
    CommitId,
    InstallationId,
    PRNumber,
    RepoName,
    RepoOwner,
    UserId,
)


def createPRCtx(
    userId: UserId,
    installationId: InstallationId,
    owner: RepoOwner,
    repo: RepoName,
    prNumber: PRNumber,
    commitId: CommitId | None = None,
) -> PRCtx:
    """Assemble a :class:`PRCtx`.

    The installation-scoped client is minted here — the ctx factory is
    the I/O boundary ("edge"). Identity is validated upstream (auth
    middleware / webhook receiver), so no checks happen here.
    """
    return PRCtx(
        userId=userId,
        installationId=installationId,
        owner=owner,
        repo=repo,
        prNumber=prNumber,
        commitId=commitId,
        client=getAuthenticatedGitHubClient(installationId),
    )


def _statusOf(exc: Exception) -> int | None:
    """Return the HTTP status when the exception carries one."""
    if isinstance(exc, RequestFailed):
        return exc.response.status_code
    return None


async def getPrState(ctx: PRCtx) -> PRState | GitHubPRError:
    """Fetch the PR's current state from the GitHub API."""
    client = ctx.client

    try:
        resp = await client.rest.pulls.async_get(
            owner=ctx.owner,
            repo=ctx.repo,
            pull_number=ctx.prNumber,
        )
    except Exception as exc:
        cause = f"{type(exc).__name__}: {exc}"

        return GitHubPRError(
            message=f"failed to fetch pr state: {cause}",
            userId=ctx.userId,
            installationId=ctx.installationId,
            owner=ctx.owner,
            repo=ctx.repo,
            prNumber=ctx.prNumber,
            statusCode=_statusOf(exc),
        )

    parsed = resp.parsed_data
    if parsed is None:
        return GitHubPRError(
            message="github returned an empty pull request payload",
            userId=ctx.userId,
            installationId=ctx.installationId,
            owner=ctx.owner,
            repo=ctx.repo,
            prNumber=ctx.prNumber,
        )

    return _toPrState(parsed)


def _toPrState(parsed: PullRequest) -> PRState:
    """Project a githubkit ``PullRequest`` onto :class:`PRState`."""
    head = getattr(parsed, "head", None)
    base = getattr(parsed, "base", None)
    user = getattr(parsed, "user", None)

    return PRState(
        ghPrId=parsed.id,
        state=getattr(parsed, "state", None) or "open",
        merged=bool(getattr(parsed, "merged", False)),
        title=getattr(parsed, "title", None) or "",
        body=getattr(parsed, "body", None) or "",
        author=getattr(user, "login", None) or "",
        baseBranch=getattr(base, "ref", None) or "",
        baseSha=getattr(base, "sha", None) or "",
        headBranch=getattr(head, "ref", None) or "",
        headSha=getattr(head, "sha", None) or "",
        additions=int(getattr(parsed, "additions", 0) or 0),
        deletions=int(getattr(parsed, "deletions", 0) or 0),
        changedFiles=int(getattr(parsed, "changed_files", 0) or 0),
    )


async def addReaction(
    ctx: PRCtx,
    commentId: int,
    content: ReactionContent = "eyes",
) -> None | GitHubPRError:
    """Add a reaction to an issue comment (best-effort ack)."""
    client = ctx.client

    data: ReposOwnerRepoIssuesCommentsCommentIdReactionsPostBodyType = {
        "content": content,
    }
    try:
        await client.rest.reactions.async_create_for_issue_comment(
            owner=ctx.owner,
            repo=ctx.repo,
            comment_id=commentId,
            data=data,
        )
    except Exception as exc:
        cause = f"{type(exc).__name__}: {exc}"

        return GitHubPRError(
            message=f"failed to add reaction: {cause}",
            userId=ctx.userId,
            installationId=ctx.installationId,
            owner=ctx.owner,
            repo=ctx.repo,
            prNumber=ctx.prNumber,
            statusCode=_statusOf(exc),
        )
    return None


async def postReview(
    ctx: PRCtx,
    draft: PRReviewDraft,
) -> PullRequestReview | GitHubPRError:
    """Submit a review (verdict + summary + inline comments) on the PR.

    GitHub API only — the caller owns any local persistence. Anchors
    the review to ``ctx.commitId``.
    """
    if ctx.commitId is None:
        return GitHubPRError(
            message="pr ctx requires commitId to post a review",
            userId=ctx.userId,
            installationId=ctx.installationId,
            owner=ctx.owner,
            repo=ctx.repo,
            prNumber=ctx.prNumber,
        )

    client = ctx.client
    body: ReposOwnerRepoPullsPullNumberReviewsPostBodyType = {
        "commit_id": ctx.commitId,
        "event": draft.verdict,
        "body": draft.summary,
        "comments": [_toCommentItem(comment) for comment in draft.comments],
    }
    try:
        resp = await client.rest.pulls.async_create_review(
            owner=ctx.owner,
            repo=ctx.repo,
            pull_number=ctx.prNumber,
            data=body,
        )
    except Exception as exc:
        cause = f"{type(exc).__name__}: {exc}"
        return GitHubPRError(
            message=f"failed to post review: {cause}",
            userId=ctx.userId,
            installationId=ctx.installationId,
            owner=ctx.owner,
            repo=ctx.repo,
            prNumber=ctx.prNumber,
            statusCode=_statusOf(exc),
        )

    parsed = resp.parsed_data
    if parsed is None:
        return GitHubPRError(
            message="github returned an empty review payload",
            userId=ctx.userId,
            installationId=ctx.installationId,
            owner=ctx.owner,
            repo=ctx.repo,
            prNumber=ctx.prNumber,
        )
    return parsed


def _toCommentItem(
    draft: PRCommentDraft,
) -> ReposOwnerRepoPullsPullNumberReviewsPostBodyPropCommentsItemsType:
    """Convert one :class:`PRCommentDraft` to the GitHub body item."""
    return {
        "path": draft.fileName,
        "line": draft.line,
        "side": draft.side,
        "body": draft.body,
    }


async def postComment(ctx: PRCtx, body: str) -> IssueComment | GitHubPRError:
    """Post a comment on the PR's issue thread."""
    client = ctx.client

    data: ReposOwnerRepoIssuesIssueNumberCommentsPostBodyType = {"body": body}
    try:
        resp = await client.rest.issues.async_create_comment(
            owner=ctx.owner,
            repo=ctx.repo,
            issue_number=ctx.prNumber,
            data=data,
        )
    except Exception as exc:
        cause = f"{type(exc).__name__}: {exc}"
        return GitHubPRError(
            message=f"failed to post comment: {cause}",
            userId=ctx.userId,
            installationId=ctx.installationId,
            owner=ctx.owner,
            repo=ctx.repo,
            prNumber=ctx.prNumber,
            statusCode=_statusOf(exc),
        )

    parsed = resp.parsed_data
    if parsed is None:
        return GitHubPRError(
            message="github returned an empty comment payload",
            userId=ctx.userId,
            installationId=ctx.installationId,
            owner=ctx.owner,
            repo=ctx.repo,
            prNumber=ctx.prNumber,
        )
    return parsed


__all__ = [
    "addReaction",
    "createPRCtx",
    "getPrState",
    "postComment",
    "postReview",
]
