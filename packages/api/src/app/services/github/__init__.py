"""GitHub services module.

Submodules:

- :mod:`.installation` — sub-service: GitHub App install flow + local
  install state (install URL, installation details, list, forget).
- :mod:`.repo`        — sub-service: reading repos from GitHub (list,
  get, token, clone URL).
- :mod:`.pr`          — sub-service: pull-request events (state,
  reaction, review, comment).
- :mod:`.webhook`     — sub-service: GitHub webhook event handling
  (registry dispatch + per-event handlers).

The GitHub post-pipeline (posting a review + the back-link updates)
lives in :mod:`app.workflows.review.steps.post_review`, built on the
:mod:`.pr` sub-service.
"""

from app.services.github.installation import (
    GitHubInstallationError,
    InstallationCtx,
    InstallationDetails,
    InstallUrl,
    createInstallationCtx,
    forgetInstallation,
    getInstallUrl,
    getInstallation,
    listInstallations,
)
from app.services.github.repo import (
    GitHubRepo,
    GitHubRepoError,
    RepoCtx,
    createRepoCtx,
    getCloneUrl,
    getRepo,
    listInstallationRepos,
    mintAccessToken,
)
from app.services.github.pr import (
    GitHubPRError,
    PRCommentDraft,
    PRCtx,
    PRReviewDraft,
    PRState,
    PRVerdict,
    ReactionContent,
    addReaction,
    createPRCtx,
    getPrState,
    postComment,
    postReview,
)
from app.services.github.webhook import (
    WebhookCtx,
    WebhookHandler,
    WebhookRegistry,
    WebhookResult,
    handleInstallationDeleted,
    handleInstallationReposAdded,
    handleInstallationReposRemoved,
    handleInstallationSuspended,
    handleInstallationUnsuspended,
    handleIssueCommentCreated,
    handlePullRequestOpened,
    handlePush,
    handleWebhookEvent,
)

__all__ = [
    "GitHubInstallationError",
    "InstallationCtx",
    "InstallationDetails",
    "InstallUrl",
    "createInstallationCtx",
    "forgetInstallation",
    "getInstallUrl",
    "getInstallation",
    "listInstallations",
    "GitHubRepo",
    "GitHubRepoError",
    "RepoCtx",
    "createRepoCtx",
    "getCloneUrl",
    "getRepo",
    "listInstallationRepos",
    "mintAccessToken",
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
    "WebhookCtx",
    "WebhookHandler",
    "WebhookRegistry",
    "WebhookResult",
    "handleInstallationDeleted",
    "handleInstallationReposAdded",
    "handleInstallationReposRemoved",
    "handleInstallationSuspended",
    "handleInstallationUnsuspended",
    "handleIssueCommentCreated",
    "handlePullRequestOpened",
    "handlePush",
    "handleWebhookEvent",
]