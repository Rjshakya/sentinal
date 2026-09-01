"""Post the review to GitHub and update the DB back-links.

This supersedes the legacy ``app.services.github.workflow``
(``post_review_to_github_workflow``, removed) with two pieces inside
the main workflow:

- :func:`postReviewStep` — the **DBOS step edge**: converts the
  :class:`ReviewResult` into the GitHub body, posts it via the
  refactored :mod:`app.services.github.pr` sub-service
  (:func:`createPRCtx` + :func:`postReview`), and fetches the posted
  comment ids. Retryable failures (429 / 5xx) raise
  :class:`TransientReviewStepFailure` so DBOS retries the step; a
  final failure (4xx) **returns** a ``posted=False`` result — the
  local review still completes, so the workflow does not fail over
  it.
- :func:`updatePostBacklinksTx` — the **DBOS transaction edge**: writes
  ``review.github_review_id`` and the per-comment
  ``code_comments.github_comment_id`` back-links.

Posting is best-effort and never fails the review; the post retries
happen inside the step without re-running the LLM.
"""

from __future__ import annotations

import logging

from dbos import DBOS
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.core.db import async_session_maker
from app.models.code_comment import CodeComment
from app.models.review import Review
from app.services.github.pr.errors import GitHubPRError
from app.services.github.pr.service import createPRCtx, postReview
from app.services.github.pr.types import PRCommentDraft, PRCtx, PRReviewDraft
from app.utils.branded import CommitId, PRNumber, RepoId, ReviewRowId
from app.utils.schema import CodeCommentDraft, ReviewResult
from app.workflows.review.errors import (
    PersistError,
    PostReviewError,
    ReviewStepFailure,
    TransientReviewStepFailure,
    isRetryableStatusCode,
    shouldRetry,
)
from app.workflows.review.types import (
    PostReviewResult,
    RepoSnapshot,
    ReviewWorkflowInput,
)

log = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Pure conversions                                                             #
# --------------------------------------------------------------------------- #


def convertToGithubComments(
    comments: list[CodeCommentDraft],
) -> list[PRCommentDraft]:
    """Convert :class:`CodeCommentDraft` items to GitHub comment items.

    Drops drafts with invalid line numbers (``from_line < 1`` or
    ``to_line < 1``) because GitHub review comments require 1-based
    line numbers — the final defence-in-depth after the agents anchor
    to gutter-visible lines.
    """
    github_comments: list[PRCommentDraft] = []
    for draft in comments:
        if draft.from_line < 1 or draft.to_line < 1:
            continue
        github_comments.append(
            PRCommentDraft(
                fileName=draft.file_name,
                line=draft.from_line,
                side=draft.side,
                body=draft.comment,
            )
        )
    return github_comments


def buildPostReviewDraft(
    commitId: CommitId,
    review: ReviewResult,
) -> PRReviewDraft:
    """Build the GitHub review payload from a :class:`ReviewResult`.

    The verdict strings already match GitHub's review-event values
    (``APPROVE`` / ``COMMENT`` / ``REQUEST_CHANGES``).
    """
    return PRReviewDraft(
        verdict=review.verdict,
        summary=review.summary,
        comments=convertToGithubComments(review.comments),
    )


async def _listReviewCommentIds(
    prCtx: PRCtx,
    *,
    repoOwner: str,
    repoName: str,
    prNumber: int,
    reviewId: int,
) -> list[int] | None:
    """Fetch the posted review's comment ids (best-effort).

    Returns ``None`` when the fetch fails — the back-link update then
    only records the review id. Uses the installation client carried
    on the PR ctx; kept local until the pr sub-service grows a
    dedicated ``listReviewComments`` entry point.
    """
    client = prCtx.client
    try:
        resp = await client.rest.pulls.async_list_comments_for_review(
            owner=repoOwner,
            repo=repoName,
            pull_number=prNumber,
            review_id=reviewId,
        )
    except Exception as exc:
        log.warning(
            "post_review_step: failed to fetch review comments (continuing): "
            "pr_number=%s review_id=%s cause=%s: %s",
            prNumber,
            reviewId,
            type(exc).__name__,
            exc,
        )
        return None
    parsed = resp.parsed_data or []
    ids: list[int] = []
    for c in parsed:
        cid = getattr(c, "id", None)
        if isinstance(cid, int):
            ids.append(cid)
    return ids


@DBOS.step(
    retries_allowed=True,
    max_attempts=3,
    should_retry=shouldRetry,
    backoff_rate=2,
)
async def postReviewStep(
    *,
    repo: RepoSnapshot,
    input: ReviewWorkflowInput,
    review: ReviewResult,
) -> PostReviewResult:
    """Durable step: post the review (verdict + summary + comments) to
    GitHub.

    Raises:
        TransientReviewStepFailure: GitHub returned 429 / 5xx — DBOS
            retries the step without re-running the LLM.
    Returns:
        ``posted=True`` with the GitHub ids, or ``posted=False`` with
        the error for terminal (4xx) failures — the local review
        completes regardless.
    """
    installationId = input.githubInstallationId
    if installationId is None:
        return PostReviewResult(posted=False, error="no installation id")

    prCtx = createPRCtx(
        userId=input.userId,
        installationId=installationId,
        owner=repo.repoOwner,
        repo=repo.repoName,
        prNumber=input.prNumber,
        commitId=input.headSha,
    )

    draft = buildPostReviewDraft(input.headSha, review)

    result = await postReview(prCtx, draft)
    if isinstance(result, GitHubPRError):
        retryable = isRetryableStatusCode(result.statusCode)
        err = PostReviewError(
            message=result.message,
            userId=input.userId,
            repoId=repo.id,
            prNumber=input.prNumber,
            headSha=input.headSha,
            statusCode=result.statusCode,
            retryable=retryable,
        )
        if retryable:
            log.warning(
                "post_review_step: transient failure (will retry): "
                "pr_number=%s status=%s cause=%s",
                input.prNumber,
                result.statusCode,
                result.message,
            )
            raise TransientReviewStepFailure(err)
        log.warning(
            "post_review_step: terminal failure: pr_number=%s status=%s cause=%s",
            input.prNumber,
            result.statusCode,
            result.message,
        )
        return PostReviewResult(posted=False, error=result.message)

    githubReviewId = result.id
    commentIds = await _listReviewCommentIds(
        prCtx,
        repoOwner=repo.repoOwner,
        repoName=repo.repoName,
        prNumber=input.prNumber,
        reviewId=githubReviewId,
    )

    log.info(
        "post_review_step: ok pr_number=%s review_id=%s comments=%d",
        input.prNumber,
        githubReviewId,
        len(commentIds or []),
    )
    return PostReviewResult(
        posted=True,
        githubReviewId=githubReviewId,
        githubCommentIds=commentIds or [],
    )


async def updatePostBacklinks(
    session: AsyncSession,
    *,
    reviewRowId: ReviewRowId,
    commentRowIds: list[str],
    githubReviewId: int,
    githubCommentIds: list[int],
    repoId: RepoId,
    prNumber: PRNumber,
) -> None | PersistError:
    """Write the GitHub back-links onto the local rows.

    ``review.github_review_id`` records the posted review; the
    persisted comment rows (in insertion order) get
    ``code_comments.github_comment_id`` from the posted comment ids
    (GitHub returns them in posted order).
    """
    try:
        review = await session.get(Review, reviewRowId)
        if review is not None:
            review.github_review_id = str(githubReviewId)
            session.add(review)

        if commentRowIds and githubCommentIds:
            rows = (
                (
                    await session.execute(
                        select(CodeComment).where(
                            CodeComment.id.in_(commentRowIds)  # type: ignore[attr-defined]
                        )
                    )
                )
                .scalars()
                .all()
            )
            byId = {row.id: row for row in rows}
            for rowId, ghId in zip(commentRowIds, githubCommentIds, strict=False):
                row = byId.get(rowId)
                if row is not None:
                    row.github_comment_id = str(ghId)
                    session.add(row)

        await session.commit()
        return None
    except Exception as exc:
        return PersistError(
            message=f"failed to update post back-links: {type(exc).__name__}: {exc}",
            repoId=repoId,
            prNumber=prNumber,
        )


@DBOS.step()
async def updatePostBacklinksTx(
    *,
    reviewRowId: ReviewRowId,
    commentRowIds: list[str],
    githubReviewId: int,
    githubCommentIds: list[int],
    repoId: RepoId,
    prNumber: PRNumber,
) -> None:
    """Durable DBOS transaction: persist the GitHub back-links.

    Raises:
        ReviewStepFailure: the back-link rows could not be written
            (wrapping a :class:`PersistError`).
    """
    async with async_session_maker() as session:
        result = await updatePostBacklinks(
            session,
            reviewRowId=reviewRowId,
            commentRowIds=commentRowIds,
            githubReviewId=githubReviewId,
            githubCommentIds=githubCommentIds,
            repoId=repoId,
            prNumber=prNumber,
        )
        if result is not None:
            raise ReviewStepFailure(result)


__all__ = [
    "buildPostReviewDraft",
    "convertToGithubComments",
    "postReviewStep",
    "updatePostBacklinks",
    "updatePostBacklinksTx",
]
