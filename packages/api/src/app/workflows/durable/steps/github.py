"""GitHub-boundary steps: parse webhooks, fetch live PR, load last review.

Imports on top. Each step validates its input first, runs one operation,
returns ``model_dump(mode="json")``. Returns ``None`` for skip-cases so
handlers return early with ``ReviewSkipped``.
"""

from __future__ import annotations

import logging

from async_durable_execution import durable_callable
from langfuse import observe
from pydantic import BaseModel, ConfigDict

from app.core.db import async_session_maker
from app.repositories.review import ReviewRepository
from app.services.github.pr.errors import GitHubPRError
from app.services.github.pr.service import createPRCtx, getPrState
from app.utils.branded import (
    CommitId,
    InstallationId,
    PRNumber,
    RepoName,
    RepoOwner,
    UserId,
)
from app.workflows.triggers.comment_payload import (
    classifyComment,
    validateCommentPayload,
)
from app.workflows.triggers.opened_payload import extractOpenedPrPayload
from app.workflows.triggers.types import LastReviewSnapshot

log = logging.getLogger(__name__)


@durable_callable
@observe(name="parse-opened-payload", capture_input=False, capture_output=False)
async def parseOpenedPayload(*, payload: dict) -> dict | None:
    """Validate a pull_request payload into PRPayload dump, else None."""
    parsed = extractOpenedPrPayload(payload)
    if parsed is None:
        return None
    return parsed.model_dump(mode="json")


class CommentPayloadInput(BaseModel):
    """Validated input for comment parsing (raw payload + delivery + slug)."""

    model_config = ConfigDict(frozen=True)

    payload: dict
    delivery: str
    appSlug: str


@durable_callable
@observe(name="parse-comment-payload", capture_input=False, capture_output=False)
async def parseCommentPayload(*, input: dict) -> dict | None:
    """Validate an issue_comment payload, else None (malformed or gated)."""
    request = CommentPayloadInput.model_validate(input)
    trigger = validateCommentPayload(request.payload, delivery=request.delivery)
    if trigger is None:
        return None
    classified = classifyComment(request.payload, appSlug=request.appSlug)
    if not classified.shouldProceed:
        return None
    return trigger.model_dump(mode="json")


class LivePrStateInput(BaseModel):
    """Validated input for the live GitHub PR fetch (comment path only)."""

    model_config = ConfigDict(frozen=True)

    userId: UserId
    installationId: InstallationId
    owner: RepoOwner
    repo: RepoName
    prNumber: PRNumber


@durable_callable
@observe(name="fetch-live-pr-state", capture_input=False, capture_output=False)
async def fetchLivePrState(*, input: dict) -> dict | None:
    """Fetch the PR snapshot from GitHub, else None on API error."""
    request = LivePrStateInput.model_validate(input)
    prCtx = createPRCtx(
        request.userId,
        request.installationId,
        request.owner,
        request.repo,
        request.prNumber,
    )
    state = await getPrState(prCtx)
    if isinstance(state, GitHubPRError):
        log.warning("fetchLivePrState: github fetch failed: %s", state.message)
        return None
    return state.model_dump(mode="json")


class LastReviewInput(BaseModel):
    """Validated input for loading the latest successful review row."""

    model_config = ConfigDict(frozen=True)

    repoId: str
    prNumber: int


@durable_callable
@observe(name="load-last-review", capture_input=False, capture_output=False)
async def loadLastSuccessfulReview(*, input: dict) -> dict | None:
    """Return the last successful review snapshot dump, else None."""
    request = LastReviewInput.model_validate(input)
    async with async_session_maker() as session:
        row = await ReviewRepository(session=session).find_latest_success(
            request.repoId, request.prNumber
        )
        if row is None:
            return None
        return LastReviewSnapshot(
            commitId=CommitId(row.commit_id),
            baseSha=row.base_sha,
            createdAt=row.created_at,
            githubReviewId=row.github_review_id,
        ).model_dump(mode="json")


__all__ = [
    "fetchLivePrState",
    "loadLastSuccessfulReview",
    "parseCommentPayload",
    "parseOpenedPayload",
]
