"""PR sub-service: pull-request events against the GitHub API.

Public surface:

- :func:`createPRCtx` — ctx constructor.
- :func:`getPrState` — PR snapshot (state, merged, shas, branches).
- :func:`listPulls` — PR list (header fields only).
- :func:`listCommits` — commit list.
- :func:`listFiles` — changed files (``patch`` verbatim).
- :func:`listIssueComments` — issue-thread comments.
- :func:`listReviewComments` — inline review comments.
- :func:`listReviews` — submitted reviews.
- :func:`addReaction` — reaction on an issue comment.
- :func:`postReview` — submit a review with inline comments.
- :func:`postComment` — comment on the PR's issue thread.

Error contract: **no function raises.** Failures are returned as
:class:`GitHubPRError` values; callers discriminate with
``isinstance``.
"""

from app.services.github.pr.errors import GitHubPRError
from app.services.github.pr.service import (
    addReaction,
    createPRCtx,
    getPrState,
    listCommits,
    listFiles,
    listIssueComments,
    listPulls,
    listReviewComments,
    listReviews,
    postComment,
    postReview,
)
from app.services.github.pr.types import (
    IssueCommentItem,
    PRCommentDraft,
    PRCommitItem,
    PRCtx,
    PRFileItem,
    PRListItem,
    PRReviewDraft,
    PRReviewItem,
    PRState,
    PRVerdict,
    PullListState,
    ReactionContent,
    ReviewCommentItem,
)

__all__ = [
    "GitHubPRError",
    "IssueCommentItem",
    "PRCommentDraft",
    "PRCommitItem",
    "PRCtx",
    "PRFileItem",
    "PRListItem",
    "PRReviewDraft",
    "PRReviewItem",
    "PRState",
    "PRVerdict",
    "PullListState",
    "ReactionContent",
    "ReviewCommentItem",
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