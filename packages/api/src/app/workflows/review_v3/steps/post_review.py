"""Post the validated review to GitHub (best-effort, never raises).

Builds the GitHub payload purely from the :class:`Review` value —
summary as the body, findings as inline comments, verdict recomputed
by severity (already on the value) — and submits it via the ``pr``
sub-service. A terminal GitHub failure (4xx) returns ``posted=False``
with the error; only transport-level failures (429 / 5xx) surface as
:class:`PostError` for a future retry. Comment ids are fetched
best-effort for back-link writes elsewhere.
"""

from __future__ import annotations

from app.services.github.pr.errors import GitHubPRError
from app.services.github.pr.service import createPRCtx
from app.services.github.pr.service import postReview as postGithubReview
from app.services.github.pr.types import PRCommentDraft, PRReviewDraft
from app.utils.branded import CommitId, InstallationId, PRNumber, RepoName, RepoOwner
from app.utils.branded import UserId
from app.workflows.review_v3.errors import PostError
from app.workflows.review_v3.types import PostResult, Review

_ERROR_CHARS = 500


def _isRetryable(statusCode: int | None) -> bool:
    """429 / 5xx are transient; anything else is terminal."""
    return statusCode is not None and (
        statusCode == 429 or 500 <= statusCode < 600
    )


async def postReview(
    *,
    review: Review,
    userId: UserId,
    installationId: InstallationId,
    owner: RepoOwner,
    repo: RepoName,
    prNumber: PRNumber,
    headSha: CommitId,
) -> PostResult | PostError:
    """Submit the review; return ``PostResult`` or ``PostError``."""
    if not review.summary.strip() and not review.comments:
        return PostResult(posted=False, error="empty review: nothing to post")

    prCtx = createPRCtx(
        userId=userId,
        installationId=installationId,
        owner=owner,
        repo=repo,
        prNumber=prNumber,
        commitId=headSha,
    )
    draft = PRReviewDraft(
        verdict=review.verdict,
        summary=review.summary,
        comments=[
            PRCommentDraft(
                fileName=comment.file,
                line=comment.fromLine,
                side=comment.side,
                body=f"[{comment.severity}] {comment.body}",
            )
            for comment in review.comments
        ],
    )
    posted = await postGithubReview(prCtx, draft)
    if isinstance(posted, GitHubPRError):
        if _isRetryable(posted.statusCode):
            return PostError(message=f"github post failed: {posted.message}")
        return PostResult(
            posted=False, error=(posted.message or "github post failed")[:_ERROR_CHARS]
        )

    commentIds: list[int] = []
    try:
        resp = await prCtx.client.rest.pulls.async_list_comments_for_review(
            owner=str(owner),
            repo=str(repo),
            pull_number=int(prNumber),
            review_id=posted.id,
        )
    except Exception:
        resp = None
    if resp is not None:
        for item in resp.parsed_data or []:
            itemId = getattr(item, "id", None)
            if isinstance(itemId, int) and not isinstance(itemId, bool):
                commentIds.append(itemId)
    return PostResult(
        posted=True,
        githubReviewId=int(posted.id),
        githubCommentIds=commentIds,
    )


__all__ = ["postReview"]
