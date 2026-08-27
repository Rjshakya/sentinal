"""GitHub services module.

Submodules:

- :mod:`.post_review` — pure conversion + GitHub API posting + DB
  updates. Module-private I/O helpers used by
  :mod:`.workflow`.
- :mod:`.workflow`    — DBOS durable workflow that wraps a single
  :func:`post_review_to_github_step` and can be retried independently
  of the main review workflow.
- :mod:`.steps`       — placeholder for sub-step helpers used by
  :mod:`.workflow`.
- :mod:`.installation` — sub-service: GitHub App install flow + local
  install state (install URL, installation details, list, forget).
- :mod:`.repo`        — sub-service: reading repos from GitHub (list,
  get, token, clone URL).
- :mod:`.pr`          — sub-service: pull-request events (state,
  reaction, review, comment).
- :mod:`.webhook`     — sub-service: GitHub webhook event handling
  (registry dispatch + per-event handlers).
"""

from app.services.github.post_review import (
    GitHubAuthFailed,
    GitHubCommentPostFailed,
    GitHubPRNotFound,
    GitHubPosterError,
    GitHubRateLimited,
    GitHubReviewPostFailed,
    build_github_review_body,
    convert_to_github_comments,
    convert_to_github_event,
    post_review_and_update_db,
    post_review_to_github,
    update_github_comment_ids,
    update_github_review_id,
)
from app.services.github.workflow import (
    NonRetryableGitHubPostError,
    RetryableGitHubPostError,
    post_review_to_github_step,
    post_review_to_github_workflow,
)
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
    "GitHubPosterError",
    "GitHubReviewPostFailed",
    "GitHubAuthFailed",
    "GitHubRateLimited",
    "GitHubPRNotFound",
    "GitHubCommentPostFailed",
    "convert_to_github_event",
    "convert_to_github_comments",
    "build_github_review_body",
    "post_review_to_github",
    "update_github_review_id",
    "update_github_comment_ids",
    "post_review_and_update_db",
    "RetryableGitHubPostError",
    "NonRetryableGitHubPostError",
    "post_review_to_github_step",
    "post_review_to_github_workflow",
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
