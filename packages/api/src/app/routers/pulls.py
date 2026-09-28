"""Pulls routes: live GitHub PR reads plus the local Sentinel mirror.

All endpoints are user-scoped: they read ``request.state.user_id`` (set by
``AuthMiddleware``) and resolve ``{owner}/{repo}`` in two steps:

1. The local :class:`Repo` row via
   :meth:`RepoRepository.find_by_owner_name` (exact match, then a
   case-insensitive fallback since GitHub logins are case-insensitive).
2. The active :class:`Installation` row by matching ``account_login``
   against ``owner`` case-insensitively
   (:meth:`InstallationRepository.find_by_user` filtered in Python).

The installation-scoped ``githubkit`` client is minted per request via
:func:`createPRCtx`. GitHub payloads pass through verbatim — ``patch``
``None`` stays ``None``. Sentinel data (local ``review`` /
``review_summaries`` / ``code_comments`` / ``review_usages`` rows) is
attached on the detail and sentinel endpoints only.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request
from pydantic import BaseModel, Field
from sqlmodel import col
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.db import get_session
from app.models.repo import Repo
from app.repositories.code_comment import CodeCommentRepository
from app.repositories.installation import InstallationRepository
from app.repositories.pull_request import PullRequestRepository
from app.repositories.repo import RepoRepository
from app.repositories.review import ReviewRepository
from app.repositories.review_summary import ReviewSummaryRepository
from app.repositories.review_usage import ReviewUsageRepository
from app.services.github.pr import (
    GitHubPRError,
    IssueCommentItem,
    PRCommitItem,
    PRCtx,
    PRFileItem,
    PRListItem,
    PRReviewItem,
    PRState,
    ReviewCommentItem,
    createPRCtx,
    getPrState,
    listCommits,
    listFiles,
    listIssueComments,
    listPulls,
    listReviewComments,
    listReviews,
)
from app.utils.branded import InstallationId, PRNumber, RepoName, RepoOwner, UserId

router = APIRouter(prefix="/pulls", tags=["pulls"])

PullsStateQuery = Literal["open", "closed", "all"]


# --------------------------------------------------------------------------- #
# Response models                                                             #
# --------------------------------------------------------------------------- #


class SentinelRefOut(BaseModel):
    """Pointer to the latest Sentinel run for a PR (detail header)."""

    reviewId: str | None = None
    state: str | None = None
    verdict: str | None = None
    commentCount: int | None = None
    commitId: str | None = None
    createdAt: datetime | None = None


class PullDetailOut(BaseModel):
    """PR header: live GitHub state plus the local row pointers."""

    owner: str
    repo: str
    number: int
    github: PRState
    localPrId: str | None = None
    sentinel: SentinelRefOut | None = None


class PullFilesOut(BaseModel):
    """Changed-files page: verbatim GitHub entries plus the PR total."""

    files: list[PRFileItem] = Field(default_factory=list)
    total: int


class ConversationOut(BaseModel):
    """Conversation tab: issue comments + inline comments + reviews."""

    issueComments: list[IssueCommentItem] = Field(default_factory=list)
    reviewComments: list[ReviewCommentItem] = Field(default_factory=list)
    reviews: list[PRReviewItem] = Field(default_factory=list)


class SentinelReviewOut(BaseModel):
    id: str
    state: str
    trigger: str | None = None
    commitId: str
    commentCount: int | None = None
    llmClient: str | None = None
    llmModel: str | None = None
    startedAt: datetime | None = None
    completedAt: datetime | None = None
    createdAt: datetime


class SentinelSummaryOut(BaseModel):
    summary: str
    verdict: str
    commitId: str
    githubReviewId: str | None = None
    createdAt: datetime


class SentinelCommentOut(BaseModel):
    id: str
    fileName: str
    comment: str
    severity: str
    fromLine: int
    toLine: int
    side: str
    nodeType: str | None = None
    state: str
    createdAt: datetime


class SentinelUsageOut(BaseModel):
    inputTokens: int
    outputTokens: int
    totalTokens: int
    reviewStatus: str


class SentinelDetailOut(BaseModel):
    """Sentinel tab: one local review run with summary/comments/usage."""

    review: SentinelReviewOut | None = None
    summary: SentinelSummaryOut | None = None
    comments: list[SentinelCommentOut] = Field(default_factory=list)
    usage: SentinelUsageOut | None = None


# --------------------------------------------------------------------------- #
# Helpers                                                                     #
# --------------------------------------------------------------------------- #


def _githubErrorToHttp(err: GitHubPRError) -> HTTPException:
    """Map a :class:`GitHubPRError` to an HTTP error (status passthrough)."""
    status = err.statusCode
    if status in (400, 401, 403, 404, 409, 422):
        return HTTPException(status_code=status, detail=err.message)
    return HTTPException(status_code=502, detail=err.message)


async def _resolvePrCtx(
    session: AsyncSession,
    *,
    userId: str,
    owner: str,
    repo: str,
    prNumber: int,
) -> tuple[Repo, PRCtx]:
    """Resolve the local repo row + installation-scoped :class:`PRCtx`.

    Raises 404 when the repo row is missing or no active installation
    covers ``owner``. GitHub logins are case-insensitive, so both
    lookups fall back to a case-insensitive match.
    """
    repos = RepoRepository(session=session)
    row = await repos.find_by_owner_name(userId, owner, repo)
    if row is None:
        candidates = await repos.find(col(Repo.user_id) == userId)
        lowered_owner = owner.lower()
        lowered_repo = repo.lower()
        for candidate in candidates:
            if (
                candidate.repo_owner.lower() == lowered_owner
                and candidate.repo_name.lower() == lowered_repo
            ):
                row = candidate
                break
    if row is None:
        raise HTTPException(
            status_code=404, detail="repo not found or no access"
        )

    installations = InstallationRepository(session=session)
    rows = await installations.find_by_user(userId)
    lowered_owner = owner.lower()
    github_installation_id: int | None = None
    for install in rows:
        if install.suspended_at is not None:
            continue
        if install.account_login.lower() == lowered_owner:
            github_installation_id = install.github_installation_id
            break
    if github_installation_id is None:
        raise HTTPException(
            status_code=404, detail="repo not found or no access"
        )

    ctx = createPRCtx(
        UserId(userId),
        InstallationId(github_installation_id),
        RepoOwner(owner),
        RepoName(repo),
        PRNumber(prNumber),
    )
    return (row, ctx)


# --------------------------------------------------------------------------- #
# GET /api/pulls/{owner}/{repo} — PR list                                     #
# --------------------------------------------------------------------------- #


@router.get("/{owner}/{repo}", response_model=list[PRListItem])
async def list_repo_pulls(
    request: Request,
    owner: str = Path(min_length=1),
    repo: str = Path(min_length=1),
    state: PullsStateQuery = Query("open"),
    per_page: int = Query(30, ge=1, le=100),
    page: int = Query(1, ge=1),
    session: AsyncSession = Depends(get_session),
) -> list[PRListItem]:
    """List the repo's pull requests (live GitHub, header fields only)."""
    user_id: str = request.state.user_id
    _, ctx = await _resolvePrCtx(
        session, userId=user_id, owner=owner, repo=repo, prNumber=0
    )
    result = await listPulls(ctx, state=state, perPage=per_page, page=page)
    if isinstance(result, GitHubPRError):
        raise _githubErrorToHttp(result)
    return result


# --------------------------------------------------------------------------- #
# GET /api/pulls/{owner}/{repo}/{number} — detail header                      #
# --------------------------------------------------------------------------- #


@router.get("/{owner}/{repo}/{number}", response_model=PullDetailOut)
async def get_pull_detail(
    request: Request,
    owner: str = Path(min_length=1),
    repo: str = Path(min_length=1),
    number: int = Path(ge=1),
    session: AsyncSession = Depends(get_session),
) -> PullDetailOut:
    """Return the PR header: live GitHub state + local Sentinel pointer."""
    user_id: str = request.state.user_id
    repo_row, ctx = await _resolvePrCtx(
        session, userId=user_id, owner=owner, repo=repo, prNumber=number
    )

    state = await getPrState(ctx)
    if isinstance(state, GitHubPRError):
        raise _githubErrorToHttp(state)

    pr_repo = PullRequestRepository(session=session)
    local_pr = await pr_repo.find_by_repo_and_number(repo_row.id, number)

    sentinel: SentinelRefOut | None = None
    if local_pr is not None:
        reviews = ReviewRepository(session=session)
        latest = await reviews.find_latest_success(repo_row.id, number)
        if latest is None:
            rows = await reviews.find(
                col(reviews.model.repo_id) == repo_row.id,
                col(reviews.model.pr_number) == number,
                order_by=col(reviews.model.created_at).desc(),
                limit=1,
            )
            latest = rows[0] if rows else None
        if latest is not None:
            verdict: str | None = None
            summaries = ReviewSummaryRepository(session=session)
            summary = await summaries.find_by_review_id(latest.id)
            if summary is not None:
                verdict = summary.verdict
            sentinel = SentinelRefOut(
                reviewId=latest.id,
                state=latest.state,
                verdict=verdict,
                commentCount=latest.comment_count,
                commitId=latest.commit_id,
                createdAt=latest.created_at,
            )

    return PullDetailOut(
        owner=owner,
        repo=repo,
        number=number,
        github=state,
        localPrId=local_pr.id if local_pr is not None else None,
        sentinel=sentinel,
    )


# --------------------------------------------------------------------------- #
# GET /api/pulls/{owner}/{repo}/{number}/commits                              #
# --------------------------------------------------------------------------- #


@router.get("/{owner}/{repo}/{number}/commits", response_model=list[PRCommitItem])
async def get_pull_commits(
    request: Request,
    owner: str = Path(min_length=1),
    repo: str = Path(min_length=1),
    number: int = Path(ge=1),
    per_page: int = Query(30, ge=1, le=100),
    page: int = Query(1, ge=1),
    session: AsyncSession = Depends(get_session),
) -> list[PRCommitItem]:
    """List the PR's commits, oldest first (live GitHub)."""
    user_id: str = request.state.user_id
    _, ctx = await _resolvePrCtx(
        session, userId=user_id, owner=owner, repo=repo, prNumber=number
    )
    result = await listCommits(ctx, perPage=per_page, page=page)
    if isinstance(result, GitHubPRError):
        raise _githubErrorToHttp(result)
    return result


# --------------------------------------------------------------------------- #
# GET /api/pulls/{owner}/{repo}/{number}/files                                #
# --------------------------------------------------------------------------- #


@router.get("/{owner}/{repo}/{number}/files", response_model=PullFilesOut)
async def get_pull_files(
    request: Request,
    owner: str = Path(min_length=1),
    repo: str = Path(min_length=1),
    number: int = Path(ge=1),
    per_page: int = Query(30, ge=1, le=100),
    page: int = Query(1, ge=1),
    session: AsyncSession = Depends(get_session),
) -> PullFilesOut:
    """List the PR's changed files (live GitHub, ``patch`` verbatim)."""
    user_id: str = request.state.user_id
    _, ctx = await _resolvePrCtx(
        session, userId=user_id, owner=owner, repo=repo, prNumber=number
    )
    files = await listFiles(ctx, perPage=per_page, page=page)
    if isinstance(files, GitHubPRError):
        raise _githubErrorToHttp(files)

    state = await getPrState(ctx)
    if isinstance(state, GitHubPRError):
        raise _githubErrorToHttp(state)

    return PullFilesOut(files=files, total=state.changedFiles)


# --------------------------------------------------------------------------- #
# GET /api/pulls/{owner}/{repo}/{number}/conversation                         #
# --------------------------------------------------------------------------- #


@router.get(
    "/{owner}/{repo}/{number}/conversation", response_model=ConversationOut
)
async def get_pull_conversation(
    request: Request,
    owner: str = Path(min_length=1),
    repo: str = Path(min_length=1),
    number: int = Path(ge=1),
    per_page: int = Query(30, ge=1, le=100),
    page: int = Query(1, ge=1),
    session: AsyncSession = Depends(get_session),
) -> ConversationOut:
    """Return the Conversation tab (live GitHub: comments + reviews)."""
    user_id: str = request.state.user_id
    _, ctx = await _resolvePrCtx(
        session, userId=user_id, owner=owner, repo=repo, prNumber=number
    )

    issue_comments = await listIssueComments(ctx, perPage=per_page, page=page)
    if isinstance(issue_comments, GitHubPRError):
        raise _githubErrorToHttp(issue_comments)

    review_comments = await listReviewComments(ctx, perPage=per_page, page=page)
    if isinstance(review_comments, GitHubPRError):
        raise _githubErrorToHttp(review_comments)

    pr_reviews = await listReviews(ctx, perPage=per_page, page=page)
    if isinstance(pr_reviews, GitHubPRError):
        raise _githubErrorToHttp(pr_reviews)

    return ConversationOut(
        issueComments=issue_comments,
        reviewComments=review_comments,
        reviews=pr_reviews,
    )


# --------------------------------------------------------------------------- #
# GET /api/pulls/{owner}/{repo}/{number}/sentinel                             #
# --------------------------------------------------------------------------- #


@router.get("/{owner}/{repo}/{number}/sentinel", response_model=SentinelDetailOut)
async def get_pull_sentinel(
    request: Request,
    owner: str = Path(min_length=1),
    repo: str = Path(min_length=1),
    number: int = Path(ge=1),
    review_id: str | None = Query(None, min_length=1),
    session: AsyncSession = Depends(get_session),
) -> SentinelDetailOut:
    """Return the Sentinel tab: one local review run + summary/comments/usage.

    Defaults to the latest ``SUCCESS`` run; falls back to the newest run
    of any state. ``review_id`` pins a specific run (must belong to the
    caller's repo row, else 404).
    """
    user_id: str = request.state.user_id
    repos = RepoRepository(session=session)
    repo_row = await repos.find_by_owner_name(user_id, owner, repo)
    if repo_row is None:
        candidates = await repos.find(col(Repo.user_id) == user_id)
        lowered_owner = owner.lower()
        lowered_repo = repo.lower()
        for candidate in candidates:
            if (
                candidate.repo_owner.lower() == lowered_owner
                and candidate.repo_name.lower() == lowered_repo
            ):
                repo_row = candidate
                break
    if repo_row is None:
        raise HTTPException(
            status_code=404, detail="repo not found or no access"
        )

    reviews = ReviewRepository(session=session)
    target = None
    if review_id is not None:
        target = await reviews.get(review_id)
        if (
            target is None
            or target.user_id != user_id
            or target.repo_id != repo_row.id
            or target.pr_number != number
        ):
            raise HTTPException(status_code=404, detail="review not found")
    else:
        target = await reviews.find_latest_success(repo_row.id, number)
        if target is None:
            rows = await reviews.find(
                col(reviews.model.repo_id) == repo_row.id,
                col(reviews.model.pr_number) == number,
                order_by=col(reviews.model.created_at).desc(),
                limit=1,
            )
            target = rows[0] if rows else None

    if target is None:
        return SentinelDetailOut()

    summaries = ReviewSummaryRepository(session=session)
    summary_row = await summaries.find_by_review_id(target.id)

    comments_repo = CodeCommentRepository(session=session)
    comment_rows = await comments_repo.find_by_review_id(
        target.id, order_by_created_at=True
    )

    usages = ReviewUsageRepository(session=session)
    usage_rows = await usages.find(
        col(usages.model.review_id) == target.id,
        limit=1,
    )
    usage_row = usage_rows[0] if usage_rows else None

    return SentinelDetailOut(
        review=SentinelReviewOut(
            id=target.id,
            state=target.state,
            trigger=target.trigger,
            commitId=target.commit_id,
            commentCount=target.comment_count,
            llmClient=target.llm_client,
            llmModel=target.llm_model,
            startedAt=target.started_at,
            completedAt=target.completed_at,
            createdAt=target.created_at,
        ),
        summary=(
            SentinelSummaryOut(
                summary=summary_row.summary,
                verdict=summary_row.verdict,
                commitId=summary_row.commit_id,
                githubReviewId=summary_row.github_review_id,
                createdAt=summary_row.created_at,
            )
            if summary_row is not None
            else None
        ),
        comments=[
            SentinelCommentOut(
                id=c.id,
                fileName=c.file_name,
                comment=c.comment,
                severity=c.severity,
                fromLine=c.from_line,
                toLine=c.to_line,
                side=c.side,
                nodeType=c.node_type,
                state=c.state,
                createdAt=c.created_at,
            )
            for c in comment_rows
        ],
        usage=(
            SentinelUsageOut(
                inputTokens=usage_row.input_tokens,
                outputTokens=usage_row.output_tokens,
                totalTokens=usage_row.total_tokens,
                reviewStatus=usage_row.review_status,
            )
            if usage_row is not None
            else None
        ),
    )


__all__ = ["router"]
