"""DBOS durable workflow that posts a review to GitHub.

Separated from the main review workflow so it can be retried
independently via the DBOS Conductor / admin server without re-running
the LLM agent. The main review workflow spawns this one with id
``post:{repo_id}:{pr_number}:{head_sha[:7]}`` once the agent + filter
are done.

This module owns:

- :class:`RetryableGitHubPostError` / :class:`NonRetryableGitHubPostError`
  — internal error variants used to signal DBOS retry semantics.
- :func:`post_review_to_github_step` — the single ``@DBOS.step`` that
  calls :func:`app.services.github.post_review.post_review_to_github`
  and converts a :class:`GitHubPosterError` into one of the retry /
  non-retry variants.
- :func:`post_review_to_github_workflow` — the top-level
  ``@DBOS.workflow`` that wraps the step and returns a
  :class:`PostReviewResult`.
"""

from __future__ import annotations

import logging

from dbos import DBOS
from githubkit_schemas.v2026_03_10.models import PullRequestReview

from app.core.github_app import installation_client
from app.core.result import Ok
from app.services.github.post_review import (
    GitHubPosterError,
    GitHubRateLimited,
    GitHubReviewPostFailed,
    post_review_to_github,
)
from app.services.review.workflow_types import PostReviewInput, PostReviewResult

log = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Internal error variants for DBOS retry semantics                             #
# --------------------------------------------------------------------------- #


class RetryableGitHubPostError(Exception):
    """Raised when a GitHub post fails with a transient (retryable) error."""

    def __init__(self, cause: str, status_code: int | None = None):
        self.cause = cause
        self.status_code = status_code
        super().__init__(cause)


class NonRetryableGitHubPostError(Exception):
    """Raised when a GitHub post fails with a non-retryable error (4xx)."""

    def __init__(self, error: GitHubPosterError):
        self.error = error
        super().__init__(str(error))


def _is_retryable_github_error(error: GitHubPosterError) -> bool:
    """Return True iff the GitHub post error should be retried.

    Retryable: 5xx, 429 rate limited. Not retryable: 401/403 auth,
    404 not found.
    """
    if isinstance(error, GitHubRateLimited):
        return True
    if isinstance(error, GitHubReviewPostFailed):
        if error.status_code is not None and error.status_code >= 500:
            return True
        if error.status_code == 429:
            return True
    return False


def _raise_github_post_error(error: GitHubPosterError) -> None:
    """Convert a :class:`GitHubPosterError` into the right exception for
    DBOS retry handling."""
    if _is_retryable_github_error(error):
        raise RetryableGitHubPostError(
            cause=getattr(error, "cause", str(error)),
            status_code=getattr(error, "status_code", None),
        )
    raise NonRetryableGitHubPostError(error)


# --------------------------------------------------------------------------- #
# DBOS step + workflow                                                          #
# --------------------------------------------------------------------------- #


@DBOS.step(
    retries_allowed=True,
    max_attempts=3,
    should_retry=lambda exc: isinstance(exc, RetryableGitHubPostError),
)
async def post_review_to_github_step(
    input: PostReviewInput,
) -> PullRequestReview:
    """Durable step: post the review to GitHub with automatic retries.

    Raises :class:`RetryableGitHubPostError` on transient failures so
    DBOS retries. Raises :class:`NonRetryableGitHubPostError` on 4xx
    so the workflow can complete cleanly.
    """
    github_client = installation_client(input.github_installation_id)
    result = await post_review_to_github(
        github_client=github_client,
        owner=input.repo_owner,
        repo=input.repo_name,
        pr_number=input.pr_number,
        commit_id=input.commit_id,
        result=input.review,
    )
    if isinstance(result, Ok):
        return result.value
    _raise_github_post_error(result.error)
    raise AssertionError("unreachable")


@DBOS.workflow()
async def post_review_to_github_workflow(
    input: PostReviewInput,
) -> PostReviewResult:
    """Durable workflow: post a review to GitHub.

    Separated from the main review workflow so it can be retried
    independently via the DBOS Conductor / the admin server without
    re-running the LLM agent.
    """
    try:
        review = await post_review_to_github_step(input)
        log.info(
            "posted review to GitHub: owner=%s repo=%s pr_number=%s review_id=%s",
            input.repo_owner,
            input.repo_name,
            input.pr_number,
            review.id,
        )
        return PostReviewResult(posted=True, github_review_id=review.id)
    except RetryableGitHubPostError as exc:
        log.warning(
            "github post failed after retries: owner=%s repo=%s pr_number=%s cause=%s",
            input.repo_owner,
            input.repo_name,
            input.pr_number,
            exc.cause,
        )
        return PostReviewResult(posted=False, error=exc.cause)
    except NonRetryableGitHubPostError as exc:
        log.warning(
            "github post non-retryable error: owner=%s repo=%s pr_number=%s error=%s",
            input.repo_owner,
            input.repo_name,
            input.pr_number,
            exc.error,
        )
        return PostReviewResult(posted=False, error=str(exc.error))


__all__ = [
    "NonRetryableGitHubPostError",
    "RetryableGitHubPostError",
    "post_review_to_github_step",
    "post_review_to_github_workflow",
]
