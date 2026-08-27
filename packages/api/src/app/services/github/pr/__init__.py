"""PR sub-service: pull-request events against the GitHub API.

Public surface:

- :func:`createPRCtx` — ctx constructor.
- :func:`getPrState` — PR snapshot (state, merged, shas, branches).
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
    postComment,
    postReview,
)
from app.services.github.pr.types import (
    PRCommentDraft,
    PRCtx,
    PRReviewDraft,
    PRState,
    PRVerdict,
    ReactionContent,
)

__all__ = [
    "GitHubPRError",
    "PRCommentDraft",
    "PRCtx",
    "PRReviewDraft",
    "PRState",
    "PRVerdict",
    "ReactionContent",
    "addReaction",
    "createPRCtx",
    "getPrState",
    "postComment",
    "postReview",
]