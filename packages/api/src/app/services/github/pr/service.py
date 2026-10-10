"""PR sub-service: pull-request events against the GitHub API.

Entry points (camelCase, matching the package convention):

- :func:`createPRCtx` — ctx factory: mints the installation client
  and assembles the ctx (the I/O boundary).
- :func:`getPrState` — PR snapshot via ``GET /pulls/{number}``.
- :func:`listPulls` — PR list via ``GET /pulls`` (header fields only).
- :func:`listCommits` — commit list via ``GET /pulls/{n}/commits``.
- :func:`listFiles` — file list via ``GET /pulls/{n}/files``
  (``patch`` passed through verbatim, ``None`` stays ``None``).
- :func:`listIssueComments` — conversation comments via
  ``GET /issues/{n}/comments``.
- :func:`listReviewComments` — inline comments via
  ``GET /pulls/{n}/comments``.
- :func:`listReviews` — submitted reviews via
  ``GET /pulls/{n}/reviews``.
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

from datetime import datetime

from githubkit.exception import RequestFailed
from githubkit_schemas.v2026_03_10.models import (
    Commit,
    DiffEntry,
    IssueComment,
    PullRequest,
    PullRequestReview,
    PullRequestReviewComment,
    PullRequestSimple,
)
from githubkit_schemas.v2026_03_10.types import (
    ReposOwnerRepoIssuesCommentsCommentIdReactionsPostBodyType,
    ReposOwnerRepoIssuesIssueNumberCommentsPostBodyType,
    ReposOwnerRepoPullsPullNumberReviewsPostBodyPropCommentsItemsType,
    ReposOwnerRepoPullsPullNumberReviewsPostBodyType,
)

from langfuse import observe

from app.services.github.client import getAuthenticatedGitHubClient
from app.services.github.pr.errors import GitHubPRError
from app.services.github.pr.types import (
    IssueCommentItem,
    PRCommitItem,
    PRCommentDraft,
    PRCtx,
    PRFileItem,
    PRListItem,
    PRReviewDraft,
    PRReviewItem,
    PRState,
    PullListState,
    ReactionContent,
    ReviewCommentItem,
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


@observe(name="github-get-pr-state", capture_input=False, capture_output=False)
async def getPrState(ctx: PRCtx) -> PRState | GitHubPRError:
    """Fetch the PR's current state from the GitHub API."""
    try:
        from langfuse import get_client

        get_client().update_current_span(
            metadata={
                "github_owner": str(ctx.owner),
                "github_repo": str(ctx.repo),
                "github_pr_number": int(ctx.prNumber),
            }
        )
    except Exception:
        pass
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


def _str(value: object, default: str = "") -> str:
    """Narrow an ``Any``-typed payload field to ``str``."""
    return value if isinstance(value, str) else default


def _optStr(value: object) -> str | None:
    """Narrow an ``Any``-typed payload field to ``str | None``."""
    return value if isinstance(value, str) else None


def _int(value: object, default: int = 0) -> int:
    """Narrow an ``Any``-typed payload field to ``int``."""
    if isinstance(value, bool):
        return int(value)
    return value if isinstance(value, int) else default


def _optInt(value: object) -> int | None:
    """Narrow an ``Any``-typed payload field to ``int | None``."""
    if isinstance(value, bool):
        return None
    return value if isinstance(value, int) else None


def _optDatetime(value: object) -> datetime | None:
    """Narrow an ``Any``-typed payload field to ``datetime | None``."""
    return value if isinstance(value, datetime) else None


def _loginOf(user: object) -> str:
    """Return the ``login`` of a ``SimpleUser`` payload, else ``""``."""
    login = getattr(user, "login", None)
    return login if isinstance(login, str) else ""


def _avatarOf(user: object) -> str | None:
    """Return the ``avatar_url`` of a ``SimpleUser`` payload, else ``None``."""
    avatar = getattr(user, "avatar_url", None)
    return avatar if isinstance(avatar, str) else None


def _newPrError(ctx: PRCtx, message: str, exc: Exception | None = None) -> GitHubPRError:
    """Build a :class:`GitHubPRError` carrying the ctx identity."""
    return GitHubPRError(
        message=message,
        userId=ctx.userId,
        installationId=ctx.installationId,
        owner=ctx.owner,
        repo=ctx.repo,
        prNumber=ctx.prNumber,
        statusCode=_statusOf(exc) if exc is not None else None,
    )


def _toPRListItem(parsed: PullRequestSimple) -> PRListItem:
    """Project a githubkit ``PullRequestSimple`` onto :class:`PRListItem`."""
    head = getattr(parsed, "head", None)
    base = getattr(parsed, "base", None)
    user = getattr(parsed, "user", None)
    draft = getattr(parsed, "draft", False)

    return PRListItem(
        number=_int(getattr(parsed, "number", 0)),
        title=_str(getattr(parsed, "title", "")),
        body=_str(getattr(parsed, "body", "")),
        author=_loginOf(user),
        authorAvatar=_avatarOf(user),
        state=_str(getattr(parsed, "state", "open"), "open"),
        draft=draft if isinstance(draft, bool) else False,
        baseBranch=_str(getattr(base, "ref", "")),
        headBranch=_str(getattr(head, "ref", "")),
        headSha=_str(getattr(head, "sha", "")),
        createdAt=_optDatetime(getattr(parsed, "created_at", None)),
        updatedAt=_optDatetime(getattr(parsed, "updated_at", None)),
        closedAt=_optDatetime(getattr(parsed, "closed_at", None)),
        mergedAt=_optDatetime(getattr(parsed, "merged_at", None)),
        htmlUrl=_optStr(getattr(parsed, "html_url", None)),
    )


def _toPRCommitItem(parsed: Commit) -> PRCommitItem:
    """Project a githubkit ``Commit`` onto :class:`PRCommitItem`."""
    inner = getattr(parsed, "commit", None)
    gitAuthor = getattr(inner, "author", None)
    login = _loginOf(getattr(parsed, "author", None))
    if not login:
        login = _loginOf(getattr(parsed, "committer", None))

    return PRCommitItem(
        sha=_str(getattr(parsed, "sha", "")),
        message=_str(getattr(inner, "message", "")),
        authorLogin=login,
        authorAvatar=_avatarOf(getattr(parsed, "author", None)),
        authorName=_str(getattr(gitAuthor, "name", login), login),
        date=_optDatetime(getattr(gitAuthor, "date", None)),
        htmlUrl=_optStr(getattr(parsed, "html_url", None)),
    )


def _toPRFileItem(parsed: DiffEntry) -> PRFileItem:
    """Project a githubkit ``DiffEntry`` onto :class:`PRFileItem`.

    ``patch`` is verbatim from GitHub — ``None`` stays ``None``.
    """
    return PRFileItem(
        sha=_str(getattr(parsed, "sha", "")),
        filename=_str(getattr(parsed, "filename", "")),
        status=_str(getattr(parsed, "status", "")),
        additions=_int(getattr(parsed, "additions", 0)),
        deletions=_int(getattr(parsed, "deletions", 0)),
        changes=_int(getattr(parsed, "changes", 0)),
        patch=_optStr(getattr(parsed, "patch", None)),
        blobUrl=_optStr(getattr(parsed, "blob_url", None)),
        rawUrl=_optStr(getattr(parsed, "raw_url", None)),
        previousFilename=_optStr(getattr(parsed, "previous_filename", None)),
    )


def _toIssueCommentItem(parsed: IssueComment) -> IssueCommentItem:
    """Project a githubkit ``IssueComment`` onto :class:`IssueCommentItem`."""
    user = getattr(parsed, "user", None)
    return IssueCommentItem(
        id=_int(getattr(parsed, "id", 0)),
        authorLogin=_loginOf(user),
        authorAvatar=_avatarOf(user),
        body=_str(getattr(parsed, "body", "")),
        createdAt=_optDatetime(getattr(parsed, "created_at", None)),
        updatedAt=_optDatetime(getattr(parsed, "updated_at", None)),
        htmlUrl=_optStr(getattr(parsed, "html_url", None)),
    )


def _toReviewCommentItem(parsed: PullRequestReviewComment) -> ReviewCommentItem:
    """Project a review comment onto :class:`ReviewCommentItem`."""
    user = getattr(parsed, "user", None)
    return ReviewCommentItem(
        id=_int(getattr(parsed, "id", 0)),
        authorLogin=_loginOf(user),
        authorAvatar=_avatarOf(user),
        body=_str(getattr(parsed, "body", "")),
        path=_str(getattr(parsed, "path", "")),
        line=_optInt(getattr(parsed, "line", None)),
        side=_optStr(getattr(parsed, "side", None)),
        commitId=_optStr(getattr(parsed, "commit_id", None)),
        createdAt=_optDatetime(getattr(parsed, "created_at", None)),
        updatedAt=_optDatetime(getattr(parsed, "updated_at", None)),
        htmlUrl=_optStr(getattr(parsed, "html_url", None)),
        reviewId=_optInt(getattr(parsed, "pull_request_review_id", None)),
    )


def _toPRReviewItem(parsed: PullRequestReview) -> PRReviewItem:
    """Project a githubkit ``PullRequestReview`` onto :class:`PRReviewItem`."""
    user = getattr(parsed, "user", None)
    return PRReviewItem(
        id=_int(getattr(parsed, "id", 0)),
        authorLogin=_loginOf(user),
        authorAvatar=_avatarOf(user),
        state=_str(getattr(parsed, "state", "")),
        body=_str(getattr(parsed, "body", "")),
        commitId=_optStr(getattr(parsed, "commit_id", None)),
        submittedAt=_optDatetime(getattr(parsed, "submitted_at", None)),
        htmlUrl=_optStr(getattr(parsed, "html_url", None)),
    )


def _clampPage(perPage: int, page: int) -> tuple[int, int]:
    """Clamp pagination into GitHub's accepted range (1..100 / >= 1)."""
    return (min(max(perPage, 1), 100), max(page, 1))


async def listPulls(
    ctx: PRCtx,
    *,
    state: PullListState = "open",
    perPage: int = 30,
    page: int = 1,
) -> list[PRListItem] | GitHubPRError:
    """List the repo's pull requests (header fields only)."""
    perPage, page = _clampPage(perPage, page)
    try:
        resp = await ctx.client.rest.pulls.async_list(
            owner=ctx.owner,
            repo=ctx.repo,
            state=state,
            per_page=perPage,
            page=page,
        )
    except Exception as exc:
        cause = f"{type(exc).__name__}: {exc}"
        return _newPrError(ctx, f"failed to list pulls: {cause}", exc)

    parsed = resp.parsed_data
    if parsed is None:
        return _newPrError(ctx, "github returned an empty pulls payload")
    return [_toPRListItem(item) for item in parsed]


async def listCommits(
    ctx: PRCtx,
    *,
    perPage: int = 30,
    page: int = 1,
) -> list[PRCommitItem] | GitHubPRError:
    """List the PR's commits, oldest first (GitHub's native order)."""
    perPage, page = _clampPage(perPage, page)
    try:
        resp = await ctx.client.rest.pulls.async_list_commits(
            owner=ctx.owner,
            repo=ctx.repo,
            pull_number=ctx.prNumber,
            per_page=perPage,
            page=page,
        )
    except Exception as exc:
        cause = f"{type(exc).__name__}: {exc}"
        return _newPrError(ctx, f"failed to list commits: {cause}", exc)

    parsed = resp.parsed_data
    if parsed is None:
        return _newPrError(ctx, "github returned an empty commits payload")
    return [_toPRCommitItem(item) for item in parsed]


async def listFiles(
    ctx: PRCtx,
    *,
    perPage: int = 30,
    page: int = 1,
) -> list[PRFileItem] | GitHubPRError:
    """List the PR's changed files, passing ``patch`` through verbatim."""
    perPage, page = _clampPage(perPage, page)
    try:
        resp = await ctx.client.rest.pulls.async_list_files(
            owner=ctx.owner,
            repo=ctx.repo,
            pull_number=ctx.prNumber,
            per_page=perPage,
            page=page,
        )
    except Exception as exc:
        cause = f"{type(exc).__name__}: {exc}"
        return _newPrError(ctx, f"failed to list files: {cause}", exc)

    parsed = resp.parsed_data
    if parsed is None:
        return _newPrError(ctx, "github returned an empty files payload")
    return [_toPRFileItem(item) for item in parsed]


async def listIssueComments(
    ctx: PRCtx,
    *,
    perPage: int = 30,
    page: int = 1,
) -> list[IssueCommentItem] | GitHubPRError:
    """List the PR's issue-thread comments (Conversation tab)."""
    perPage, page = _clampPage(perPage, page)
    try:
        resp = await ctx.client.rest.issues.async_list_comments(
            owner=ctx.owner,
            repo=ctx.repo,
            issue_number=ctx.prNumber,
            per_page=perPage,
            page=page,
        )
    except Exception as exc:
        cause = f"{type(exc).__name__}: {exc}"
        return _newPrError(ctx, f"failed to list issue comments: {cause}", exc)

    parsed = resp.parsed_data
    if parsed is None:
        return _newPrError(ctx, "github returned an empty issue comments payload")
    return [_toIssueCommentItem(item) for item in parsed]


async def listReviewComments(
    ctx: PRCtx,
    *,
    perPage: int = 30,
    page: int = 1,
) -> list[ReviewCommentItem] | GitHubPRError:
    """List the PR's inline review comments (Conversation tab)."""
    perPage, page = _clampPage(perPage, page)
    try:
        resp = await ctx.client.rest.pulls.async_list_review_comments(
            owner=ctx.owner,
            repo=ctx.repo,
            pull_number=ctx.prNumber,
            per_page=perPage,
            page=page,
        )
    except Exception as exc:
        cause = f"{type(exc).__name__}: {exc}"
        return _newPrError(ctx, f"failed to list review comments: {cause}", exc)

    parsed = resp.parsed_data
    if parsed is None:
        return _newPrError(ctx, "github returned an empty review comments payload")
    return [_toReviewCommentItem(item) for item in parsed]


async def listReviews(
    ctx: PRCtx,
    *,
    perPage: int = 30,
    page: int = 1,
) -> list[PRReviewItem] | GitHubPRError:
    """List the PR's submitted reviews (Conversation tab)."""
    perPage, page = _clampPage(perPage, page)
    try:
        resp = await ctx.client.rest.pulls.async_list_reviews(
            owner=ctx.owner,
            repo=ctx.repo,
            pull_number=ctx.prNumber,
            per_page=perPage,
            page=page,
        )
    except Exception as exc:
        cause = f"{type(exc).__name__}: {exc}"
        return _newPrError(ctx, f"failed to list reviews: {cause}", exc)

    parsed = resp.parsed_data
    if parsed is None:
        return _newPrError(ctx, "github returned an empty reviews payload")
    return [_toPRReviewItem(item) for item in parsed]


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


@observe(name="github-post-review", capture_input=False, capture_output=False)
async def postReview(
    ctx: PRCtx,
    draft: PRReviewDraft,
) -> PullRequestReview | GitHubPRError:
    """Submit a review (verdict + summary + inline comments) on the PR.

    GitHub API only — the caller owns any local persistence. Anchors
    the review to ``ctx.commitId``.
    """
    try:
        from langfuse import get_client

        get_client().update_current_span(
            metadata={
                "github_owner": str(ctx.owner),
                "github_repo": str(ctx.repo),
                "github_pr_number": int(ctx.prNumber),
                "comment_count": len(draft.comments),
            }
        )
    except Exception:
        pass
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
    "listCommits",
    "listFiles",
    "listIssueComments",
    "listPulls",
    "listReviewComments",
    "listReviews",
    "postComment",
    "postReview",
]
