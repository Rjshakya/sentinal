"""Pure helpers for the issue_comment trigger path.

No I/O, no DB, no clock. The comment durable handler calls these to
project the raw payload onto typed models and to short-circuit on the
first failing check.
"""

from __future__ import annotations

import re
from typing import Final

from pydantic import ValidationError

from app.utils.branded import CommitId
from app.workflows.triggers.types import (
    ClassifyCommentResult,
    CommentTriggerInput,
    LastReviewSnapshot,
)

REVIEW_MENTION_RE: Final[re.Pattern[str]] = re.compile(
    r"(?i)@(?P<slug>[\w\-.]+)\s+review\b"
)

WRITE_ASSOCIATIONS: Final[frozenset[str]] = frozenset(
    {"OWNER", "COLLABORATOR", "MEMBER"}
)


def validateCommentPayload(rawPayload: dict, *, delivery: str) -> CommentTriggerInput | None:
    issue = rawPayload.get("issue")
    if not isinstance(issue, dict):
        return None
    comment = rawPayload.get("comment")
    if not isinstance(comment, dict):
        return None
    repository = rawPayload.get("repository")
    if not isinstance(repository, dict):
        return None
    owner = repository.get("owner")
    if not isinstance(owner, dict):
        return None
    installation = rawPayload.get("installation")
    if not isinstance(installation, dict):
        return None
    issue_user = issue.get("user")
    if not isinstance(issue_user, dict):
        return None
    comment_user = comment.get("user")
    if not isinstance(comment_user, dict):
        return None

    try:
        return CommentTriggerInput.model_validate(
            {
                "delivery": delivery,
                "installationId": installation.get("id"),
                "repoOwner": owner.get("login"),
                "repoName": repository.get("name"),
                "ghRepoId": repository.get("id"),
                "defaultBranch": repository.get("default_branch"),
                "prNumber": issue.get("number"),
                "prAuthorLogin": issue_user.get("login"),
                "commenterLogin": comment_user.get("login"),
                "authorAssociation": comment.get("author_association"),
                "commentId": comment.get("id"),
                "commentBody": comment.get("body"),
            }
        )
    except ValidationError:
        return None


def isPrComment(payload: dict) -> bool:
    issue = payload.get("issue")
    if not isinstance(issue, dict):
        return False
    return issue.get("pull_request") is not None


def isSelfComment(payload: dict, appSlug: str) -> bool:
    if not appSlug:
        return False
    comment = payload.get("comment")
    if not isinstance(comment, dict):
        return False
    user = comment.get("user")
    if not isinstance(user, dict):
        return False
    commenter = user.get("login")
    if not isinstance(commenter, str):
        return False
    return commenter.lower() == appSlug.lower()


def shouldReviewComment(body: str, appSlug: str) -> bool:
    if not body or not appSlug:
        return False
    target = appSlug.lower()
    for match in REVIEW_MENTION_RE.finditer(body):
        if match.group("slug").lower() == target:
            return True
    return False


def commenterIsAuthorized(payload: dict) -> bool:
    comment = payload.get("comment")
    issue = payload.get("issue")
    if not isinstance(comment, dict) or not isinstance(issue, dict):
        return False
    comment_user = comment.get("user")
    issue_user = issue.get("user")
    commenter = comment_user.get("login") if isinstance(comment_user, dict) else None
    pr_author = issue_user.get("login") if isinstance(issue_user, dict) else None
    if (
        isinstance(commenter, str)
        and isinstance(pr_author, str)
        and commenter.lower() == pr_author.lower()
    ):
        return True
    association = comment.get("author_association")
    return isinstance(association, str) and association.upper() in WRITE_ASSOCIATIONS


def classifyComment(payload: dict, *, appSlug: str) -> ClassifyCommentResult:
    if payload.get("action") != "created":
        return ClassifyCommentResult(shouldProceed=False, skipReason="not_created")
    if not isPrComment(payload):
        return ClassifyCommentResult(shouldProceed=False, skipReason="not_a_pr")
    if isSelfComment(payload, appSlug):
        return ClassifyCommentResult(shouldProceed=False, skipReason="self_comment")
    comment = payload.get("comment")
    body = comment.get("body") if isinstance(comment, dict) else None
    if not shouldReviewComment(body if isinstance(body, str) else "", appSlug):
        return ClassifyCommentResult(shouldProceed=False, skipReason="missing_mention")
    if not commenterIsAuthorized(payload):
        return ClassifyCommentResult(
            shouldProceed=False, skipReason="unauthorized_commenter"
        )
    return ClassifyCommentResult(shouldProceed=True)


def effectiveDiffBase(
    *,
    apiBaseSha: str,
    apiHeadSha: str,
    lastReview: LastReviewSnapshot | None,
) -> CommitId | None:
    """Return the git-diff base: last reviewed head when head moved, else None."""
    if lastReview is None or lastReview.commitId == apiHeadSha:
        return None
    return lastReview.commitId


def isHeadAlreadyPosted(
    *,
    apiHeadSha: str,
    lastReview: LastReviewSnapshot | None,
) -> bool:
    """True when the last successful run reviewed this head AND posted it.

    Same-head equality alone is not enough: a run can succeed in analysis
    yet never land on GitHub (terminal post failure + exhausted repair),
    and a repeat mention is the manual retry lever for that case. The
    ``githubReviewId`` back-link distinguishes posted from merely reviewed.
    """
    return (
        lastReview is not None
        and lastReview.commitId == apiHeadSha
        and lastReview.githubReviewId is not None
    )


__all__ = [
    "REVIEW_MENTION_RE",
    "WRITE_ASSOCIATIONS",
    "classifyComment",
    "commenterIsAuthorized",
    "effectiveDiffBase",
    "isHeadAlreadyPosted",
    "isPrComment",
    "isSelfComment",
    "shouldReviewComment",
    "validateCommentPayload",
]
