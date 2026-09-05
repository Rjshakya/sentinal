"""Pure helpers for the ``issue_comment`` trigger path.

No I/O, no DBOS, no sessions, no clock. The comment trigger adapter
(:func:`app.workflows.review.triggers.handleIssueCommentCreated`) calls
these in its body to project the raw webhook payload onto typed models
and to short-circuit on the first failing check.

Public surface:

- :func:`validateCommentPayload` — project a raw payload onto
  :class:`app.workflows.review.types.CommentTriggerInput`, or ``None``
  when any field is missing / wrong-typed (never raises).
- :func:`classifyComment` — the gate that decides whether a comment
  triggers a review. Returns a
  :class:`app.workflows.review.types.ClassifyCommentResult` with the
  first failing ``skipReason`` populated.
- :func:`shouldReviewComment` — the ``@<slug> review`` regex match.
  Case-insensitive, anywhere in the body.
- :func:`isPrComment` — ``payload["issue"]["pull_request"]`` is not
  ``None``.
- :func:`isSelfComment` — the commenter's login equals the configured
  app slug (case-insensitive). Used to skip self-mentions and avoid
  feedback loops.
- :func:`commenterIsAuthorized` — the commenter is the PR author
  **or** has one of the write-access ``author_association`` values
  (``OWNER`` / ``COLLABORATOR`` / ``MEMBER``).
- :func:`effectiveDiffBase` — the pure decision behind the incremental
  re-review: given the GitHub API's base/head and the latest successful
  :class:`app.workflows.review.types.LastReviewSnapshot`, return the
  git-diff base to use (``None`` = the API's ``baseSha``).
- :data:`REVIEW_MENTION_RE` — the mention regex.
- :data:`WRITE_ASSOCIATIONS` — the ``author_association`` values that
  imply write access.
"""

from __future__ import annotations

import re
from typing import Any, Final

from pydantic import ValidationError

from app.utils.branded import CommitId
from app.workflows.review.types import (
    ClassifyCommentResult,
    CommentTriggerInput,
    LastReviewSnapshot,
)

REVIEW_MENTION_RE: Final[re.Pattern[str]] = re.compile(
    r"(?i)@(?P<slug>[\w\-.]+)\s+review\b"
)
"""Case-insensitive regex: ``@<slug> review`` with a word boundary after
``review``. ``slug`` may include word characters, hyphens, and dots
(GitHub App slugs are typically lowercase with hyphens)."""

WRITE_ASSOCIATIONS: Final[frozenset[str]] = frozenset(
    {"OWNER", "COLLABORATOR", "MEMBER"}
)
"""GitHub ``author_association`` values that imply write access to the
repo. ``CONTRIBUTOR`` is intentionally excluded because it can be a
read-only role for outside contributors; ``FIRST_TIME_CONTRIBUTOR``,
``FIRST_TIMER``, ``NONE``, ``MANNEQUIN`` are excluded for the same
reason."""


def validateCommentPayload(
    rawPayload: dict[str, Any],
    *,
    delivery: str,
) -> CommentTriggerInput | None:
    """Project the raw ``issue_comment`` payload onto a typed view.

    The pydantic schema enforces every field's type; any missing or
    wrong-typed value makes the function return ``None``. The caller
    folds that into a ``malformed_payload`` skip — never raises, like
    :func:`app.workflows.review.triggers.extractPrPayload`.
    """
    issue = rawPayload.get("issue") or {}
    comment = rawPayload.get("comment") or {}
    repository = rawPayload.get("repository") or {}
    owner = (repository.get("owner") or {}).get("login")
    installation = rawPayload.get("installation") or {}
    issue_user = issue.get("user") or {}
    comment_user = comment.get("user") or {}

    flat: dict[str, Any] = {
        "delivery": delivery,
        "installationId": installation.get("id"),
        "repoOwner": owner,
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
    try:
        return CommentTriggerInput.model_validate(flat)
    except ValidationError:
        return None


def _slugInMatch(body: str, appSlug: str) -> bool:
    """True iff any ``@<slug> review`` token in ``body`` matches ``appSlug``."""
    if not body or not appSlug:
        return False
    target = appSlug.lower()
    for match in REVIEW_MENTION_RE.finditer(body):
        if match.group("slug").lower() == target:
            return True
    return False


def shouldReviewComment(body: str, appSlug: str) -> bool:
    """Case-insensitive ``@<app_slug> review`` match, anywhere in ``body``.

    The match tolerates extra punctuation / newlines between the
    mention and the word ``review`` (e.g. ``@reviewpr,\\nplease review``)
    because :data:`REVIEW_MENTION_RE` only requires whitespace between
    them. The word boundary on ``review`` prevents false positives
    like ``@reviewpr reviews``.
    """
    return _slugInMatch(body, appSlug)


def isPrComment(payload: dict[str, Any]) -> bool:
    """True iff the ``issue_comment`` event is on a pull request.

    GitHub's ``issue_comment`` event fires for both issues and pull
    requests. The discriminator is the presence of the
    ``pull_request`` key on the ``issue`` object — it is set when
    the parent is a PR and absent otherwise.
    """
    issue = payload.get("issue") or {}
    return issue.get("pull_request") is not None


def isSelfComment(payload: dict[str, Any], appSlug: str) -> bool:
    """True iff the commenter is the bot itself (case-insensitive).

    Skips self-mentions to avoid a feedback loop where the bot's
    own replies to a comment re-trigger the review.
    """
    if not appSlug:
        return False
    commenter = ((payload.get("comment") or {}).get("user") or {}).get("login")
    if not isinstance(commenter, str):
        return False
    return commenter.lower() == appSlug.lower()


def commenterIsAuthorized(payload: dict[str, Any]) -> bool:
    """True iff the commenter may trigger a review on this PR.

    Two conditions, either of which grants access:

    1. The commenter's login equals the PR author's login
       (case-insensitive). Lets the author re-trigger a review on
       their own PR without needing collaborator access.
    2. The commenter's ``author_association`` is one of
       :data:`WRITE_ASSOCIATIONS` (``OWNER`` / ``COLLABORATOR`` /
       ``MEMBER``). These are the only associations GitHub marks as
       write-capable on the repo.
    """
    commenter = ((payload.get("comment") or {}).get("user") or {}).get("login")
    pr_author = ((payload.get("issue") or {}).get("user") or {}).get("login")
    association = (payload.get("comment") or {}).get("author_association")

    if (
        isinstance(commenter, str)
        and isinstance(pr_author, str)
        and commenter.lower() == pr_author.lower()
    ):
        return True

    if isinstance(association, str) and association.upper() in WRITE_ASSOCIATIONS:
        return True

    return False


def classifyComment(
    payload: dict[str, Any],
    *,
    appSlug: str,
) -> ClassifyCommentResult:
    """Decide whether a comment should trigger a review.

    Sequential short-circuit — the first failing check wins and sets
    ``skipReason``. Order is significant: cheap structural checks
    (action / is_pr) run first, then content checks (mention), then
    the network-independent authorization check last.
    """
    action = payload.get("action")
    if action != "created":
        return ClassifyCommentResult(shouldProceed=False, skipReason="not_created")

    if not isPrComment(payload):
        return ClassifyCommentResult(shouldProceed=False, skipReason="not_a_pr")

    if isSelfComment(payload, appSlug):
        return ClassifyCommentResult(shouldProceed=False, skipReason="self_comment")

    body = (payload.get("comment") or {}).get("body")
    body_str = body if isinstance(body, str) else ""
    if not shouldReviewComment(body_str, appSlug):
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
    """Choose the git-diff base for a comment-triggered review.

    Returns ``None`` to diff from the GitHub API's ``apiBaseSha`` —
    the first-review behaviour. That covers:

    - no prior successful review (``lastReview`` is ``None``), and
    - an unchanged head (``lastReview.commitId == apiHeadSha``), where
      the deterministic inner workflow id
      (``review:{repo}:{pr}:{head_sha[:7]}``) already dedupes the
      re-trigger to the previous run.

    When the head **has** moved, the function returns the last
    successfully reviewed head, so ``git diff lastReviewedHead...newHead``
    covers only the commits pushed since the previous review instead of
    re-reviewing the whole PR diff.
    """
    if lastReview is None or lastReview.commitId == apiHeadSha:
        return None
    return lastReview.commitId


__all__ = [
    "REVIEW_MENTION_RE",
    "WRITE_ASSOCIATIONS",
    "classifyComment",
    "commenterIsAuthorized",
    "effectiveDiffBase",
    "isPrComment",
    "isSelfComment",
    "shouldReviewComment",
    "validateCommentPayload",
]