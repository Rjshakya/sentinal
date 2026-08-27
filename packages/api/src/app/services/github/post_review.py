"""GitHub review posting module.

Handles posting review results from the pipeline to GitHub PRs using the
GitHub REST API. Converts ReviewResult to GitHub API format, posts the review,
and updates database records with returned GitHub IDs.

Functional Core / Imperative Shell pattern:
- Pure: conversion functions (ReviewResult → GitHub format)
- I/O: GitHub API calls and database updates
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from githubkit import GitHub
from githubkit.exception import RequestFailed
from githubkit_schemas.v2026_03_10.models import PullRequestReview, ReviewComment
from githubkit_schemas.v2026_03_10.types import (
    ReposOwnerRepoPullsPullNumberReviewsPostBodyPropCommentsItemsType,
    ReposOwnerRepoPullsPullNumberReviewsPostBodyType,
)
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.logging import structured_log
from app.core.result import Err, Ok, Result
from app.models.code_comment import CodeComment
from app.models.review_summary import ReviewSummary
from app.services.agent.models import CodeCommentDraft, ReviewResult, ReviewVerdictStr

log = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Error types                                                                 #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class GitHubReviewPostFailed:
    """GitHub review API call failed."""

    owner: str
    repo: str
    pr_number: int
    cause: str
    status_code: int | None = None


@dataclass(frozen=True, slots=True)
class GitHubAuthFailed:
    """GitHub authentication failed."""

    installation_id: int
    cause: str
    status_code: int | None = None


@dataclass(frozen=True, slots=True)
class GitHubRateLimited:
    """GitHub API rate limit exceeded."""

    installation_id: int
    cause: str
    status_code: int | None = None


@dataclass(frozen=True, slots=True)
class GitHubPRNotFound:
    """Pull request not found on GitHub."""

    owner: str
    repo: str
    pr_number: int
    status_code: int | None = None


@dataclass(frozen=True, slots=True)
class GitHubCommentPostFailed:
    """Individual inline comment posting failed."""

    file_name: str
    line: int
    cause: str
    status_code: int | None = None


GitHubPosterError = (
    GitHubReviewPostFailed
    | GitHubAuthFailed
    | GitHubRateLimited
    | GitHubPRNotFound
    | GitHubCommentPostFailed
)


# --------------------------------------------------------------------------- #
# Pure conversion functions                                                   #
# --------------------------------------------------------------------------- #


def convert_to_github_event(verdict: ReviewVerdictStr) -> ReviewVerdictStr:
    """Convert ReviewResult verdict to GitHub API event string.

    Maps:
    - "APPROVE" → "APPROVE"
    - "COMMENT" → "COMMENT"
    - "REQUEST_CHANGES" → "REQUEST_CHANGES"
    """
    return verdict  # Verdict strings already match GitHub API


def convert_to_github_comments(
    comments: list[CodeCommentDraft],
) -> list[ReposOwnerRepoPullsPullNumberReviewsPostBodyPropCommentsItemsType]:
    """Convert CodeCommentDraft list to GitHub API comment items.

    Maps:
    - file_name → path
    - comment → body
    - from_line → line (GitHub uses single line, we use from_line)
    - side → side (RIGHT/LEFT already match)

    Drops drafts with invalid line numbers (0 or negative) because GitHub
    review comments require 1-based line numbers.
    """
    github_comments: list[
        ReposOwnerRepoPullsPullNumberReviewsPostBodyPropCommentsItemsType
    ] = []
    for draft in comments:
        if draft.from_line < 1 or draft.to_line < 1:
            continue
        github_comments.append(
            {
                "path": draft.file_name,
                "line": draft.from_line,
                "side": draft.side,
                "body": draft.comment,
            }
        )
    return github_comments


def build_github_review_body(
    result: ReviewResult,
    commit_id: str,
) -> ReposOwnerRepoPullsPullNumberReviewsPostBodyType:
    """Build GitHub review request body from ReviewResult."""
    return {
        "commit_id": commit_id,
        "event": convert_to_github_event(result.verdict),
        "body": result.summary,
        "comments": convert_to_github_comments(result.comments),
    }


# --------------------------------------------------------------------------- #
# GitHub API posting functions                                                 #
# --------------------------------------------------------------------------- #


async def post_review_to_github(
    *,
    github_client: GitHub,
    owner: str,
    repo: str,
    pr_number: int,
    commit_id: str,
    result: ReviewResult,
) -> Result[PullRequestReview, GitHubPosterError]:
    """Post a review to GitHub using the REST API.

    Args:
        github_client: Installation-scoped GitHub client
        owner: Repository owner
        repo: Repository name
        pr_number: Pull request number
        commit_id: SHA of the commit to review
        result: ReviewResult from the pipeline

    Returns:
        Ok with GitHub API response on success
        Err with specific error variant on failure
    """
    review_body = build_github_review_body(result, commit_id)

    try:
        response = await github_client.rest.pulls.async_create_review(
            owner=owner,
            repo=repo,
            pull_number=pr_number,
            data=review_body,
        )

        parsed = response.parsed_data
        if parsed is None:
            return Err(
                GitHubReviewPostFailed(
                    owner=owner,
                    repo=repo,
                    pr_number=pr_number,
                    cause="GitHub returned empty response",
                    status_code=None,
                )
            )

        log.info(
            "Posted review to GitHub: owner=%s repo=%s pr_number=%s review_id=%s",
            owner,
            repo,
            pr_number,
            parsed.id,
        )
        return Ok(parsed)

    except Exception as exc:
        error_cause = f"{type(exc).__name__}: {exc}"
        error_msg = str(exc).lower()

        status_code: int | None = None
        response_body: str | None = None
        if isinstance(exc, RequestFailed):
            status_code = exc.response.status_code
            response_body = exc.response.text

        installation_id: int | None = (
            github_client.auth.installation_id
            if hasattr(github_client.auth, "installation_id")
            else None
        )

        # Classify error types
        if "401" in error_msg or "403" in error_msg or "auth" in error_msg:
            error_type = "auth"
            err_result: GitHubPosterError = GitHubAuthFailed(
                installation_id=installation_id or 0,
                cause=error_cause,
                status_code=status_code,
            )
        elif "404" in error_msg:
            error_type = "not_found"
            err_result = GitHubPRNotFound(
                owner=owner,
                repo=repo,
                pr_number=pr_number,
                status_code=status_code,
            )
        elif "rate limit" in error_msg or "403" in error_msg:
            error_type = "rate_limited"
            err_result = GitHubRateLimited(
                installation_id=installation_id or 0,
                cause=error_cause,
                status_code=status_code,
            )
        else:
            error_type = "post_failed"
            err_result = GitHubReviewPostFailed(
                owner=owner,
                repo=repo,
                pr_number=pr_number,
                cause=error_cause,
                status_code=status_code,
            )

        structured_log(
            "ERROR",
            "github_review_post_failed",
            {
                "owner": owner,
                "repo": repo,
                "pr_number": pr_number,
                "commit_id": commit_id,
                "installation_id": installation_id,
                "error_type": error_type,
                "status_code": status_code,
                "error_message": error_cause,
                "response_body": response_body,
                "request_body": review_body,
            },
        )

        return Err(err_result)


# --------------------------------------------------------------------------- #
# Database update functions                                                    #
# --------------------------------------------------------------------------- #


async def update_github_review_id(
    session: AsyncSession,
    *,
    review_summary: ReviewSummary,
    github_review_id: int,
) -> ReviewSummary:
    """Update ReviewSummary with the returned GitHub review ID."""
    review_summary.github_review_id = str(github_review_id)
    session.add(review_summary)
    log.info(
        "Updated review summary with GitHub review ID: summary_id=%s github_review_id=%s",
        review_summary.id,
        github_review_id,
    )
    return review_summary


async def update_github_comment_ids(
    session: AsyncSession,
    *,
    code_comments: list[CodeComment],
    github_comments: list[ReviewComment],
) -> list[CodeComment]:
    """Update CodeComment rows with returned GitHub comment IDs.

    GitHub returns review comments in the same order as they were sent.
    We map them back to our CodeComment rows by index.
    """
    for i, code_comment in enumerate(code_comments):
        if i < len(github_comments):
            github_comment = github_comments[i]
            if github_comment and hasattr(github_comment, "id"):
                code_comment.github_comment_id = str(github_comment.id)
                session.add(code_comment)
                log.debug(
                    "Updated code comment with GitHub comment ID: comment_id=%s github_comment_id=%s",
                    code_comment.id,
                    github_comment.id,
                )

    log.info(
        "Updated %d code comments with GitHub comment IDs",
        len([c for c in code_comments if c.github_comment_id]),
    )
    return code_comments


# --------------------------------------------------------------------------- #
# Main orchestrator                                                            #
# --------------------------------------------------------------------------- #


async def post_review_and_update_db(
    *,
    session: AsyncSession,
    github_client: GitHub,
    owner: str,
    repo: str,
    pr_number: int,
    commit_id: str,
    result: ReviewResult,
    review_summary: ReviewSummary,
    code_comments: list[CodeComment],
) -> Result[PullRequestReview, GitHubPosterError]:
    """Orchestrate GitHub review posting and database updates.

    Sequence:
    1. Post review to GitHub API
    2. Update ReviewSummary.github_review_id
    3. Update CodeComment.github_comment_id for each comment
    4. Commit database changes

    Returns:
        Ok with GitHub API response on success
        Err with specific error variant on failure
    """
    # 1. Post to GitHub
    github_result = await post_review_to_github(
        github_client=github_client,
        owner=owner,
        repo=repo,
        pr_number=pr_number,
        commit_id=commit_id,
        result=result,
    )

    if isinstance(github_result, Err):
        return Err(github_result.error)

    github_response = github_result.value

    # 2. Update review summary
    await update_github_review_id(
        session,
        review_summary=review_summary,
        github_review_id=github_response.id,
    )

    # 3. Update code comments
    if code_comments:
        try:
            comments_response = (
                await github_client.rest.pulls.async_list_comments_for_review(
                    owner=owner,
                    repo=repo,
                    pull_number=pr_number,
                    review_id=github_response.id,
                )
            )
            await update_github_comment_ids(
                session,
                code_comments=code_comments,
                github_comments=comments_response.parsed_data or [],
            )
        except Exception as exc:
            error_cause = (
                f"Failed to fetch review comments: {type(exc).__name__}: {exc}"
            )

            status_code: int | None = None
            response_body: str | None = None
            if isinstance(exc, RequestFailed):
                status_code = exc.response.status_code
                response_body = exc.response.text

            installation_id: int | None = (
                github_client.auth.installation_id
                if hasattr(github_client.auth, "installation_id")
                else None
            )

            structured_log(
                "ERROR",
                "github_review_comments_fetch_failed",
                {
                    "owner": owner,
                    "repo": repo,
                    "pr_number": pr_number,
                    "review_id": github_response.id,
                    "installation_id": installation_id,
                    "error_type": "comment_fetch",
                    "status_code": status_code,
                    "error_message": error_cause,
                    "response_body": response_body,
                },
            )

            return Err(
                GitHubReviewPostFailed(
                    owner=owner,
                    repo=repo,
                    pr_number=pr_number,
                    cause=error_cause,
                )
            )

    # 4. Commit database changes
    await session.commit()

    log.info(
        "Successfully posted review and updated database: owner=%s repo=%s pr_number=%s review_id=%s",
        owner,
        repo,
        pr_number,
        github_response.id,
    )

    return Ok(github_response)


__all__: list[str] = [
    "GitHubAuthFailed",
    "GitHubCommentPostFailed",
    "GitHubPRNotFound",
    "GitHubPosterError",
    "GitHubRateLimited",
    "GitHubReviewPostFailed",
    "build_github_review_body",
    "convert_to_github_comments",
    "convert_to_github_event",
    "post_review_and_update_db",
    "post_review_to_github",
    "update_github_comment_ids",
    "update_github_review_id",
]
