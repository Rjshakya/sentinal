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
]
