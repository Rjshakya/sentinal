"""Pure helpers for the ``issue_comment`` trigger pipeline.

No I/O, no DBOS, no sessions, no clock. The trigger workflow calls
these in its body to project the raw webhook payload onto typed
models and to short-circuit on the first failing check.

Public surface:

- :func:`validate_comment_payload` — project a raw payload onto
  :class:`app.services.pr_issue_comment.types.IssueCommentTriggerInput`.
  Raises :class:`pydantic.ValidationError` on any malformed input;
  the workflow converts that to a ``malformed_payload`` skip.
- :func:`classify_comment` — the gate that decides whether a
  comment triggers a review. Returns a
  :class:`app.services.pr_issue_comment.types.ClassifyCommentResult`
  with the first failing ``skip_reason`` populated.
- :func:`should_review_comment` — the ``@<slug> review`` regex
  match. Case-insensitive, anywhere in the body.
- :func:`is_pr_comment` — ``payload["issue"]["pull_request"]`` is
  not None.
- :func:`is_self_comment` — the commenter's login equals the
  configured app slug (case-insensitive). Used to skip self-mentions
  and avoid feedback loops.
- :func:`commenter_is_authorized` — the commenter is the PR
  author **or** has one of the write-access ``author_association``
  values (``OWNER`` / ``COLLABORATOR`` / ``MEMBER``).
- :func:`build_review_workflow_input` — translate the trigger input
  plus the fetched PR state into the existing
  :class:`app.services.review.workflow_types.ReviewWorkflowInput`
  that :func:`app.services.review.workflow.review_workflow` already
  consumes.
- :data:`WRITE_ASSOCIATIONS` — frozenset of GitHub
  ``author_association`` values that imply write access.
"""

from __future__ import annotations

import re
from typing import Any, Final

from pydantic import ValidationError

from app.core.llm import LLMConfig
from app.models.enums import PRStatus
from app.services.pr_issue_comment.types import (
    ClassifyCommentResult,
    IssueCommentTriggerInput,
)
from app.services.review.workflow_types import PRSizeStats, ReviewWorkflowInput

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


def validate_comment_payload(
    raw_payload: dict[str, Any],
    *,
    delivery: str,
) -> IssueCommentTriggerInput:
    """Project the raw ``issue_comment`` payload onto a typed view.

    The pydantic schema enforces every field's type; any missing or
    wrong-typed value raises :class:`pydantic.ValidationError`. The
    workflow catches that and returns ``skip_reason="malformed_payload"``.

    Returns:
        The typed :class:`IssueCommentTriggerInput`.

    Raises:
        ValidationError: at least one field failed pydantic validation.
    """
    issue = raw_payload.get("issue") or {}
    comment = raw_payload.get("comment") or {}
    repository = raw_payload.get("repository") or {}
    owner = (repository.get("owner") or {}).get("login")
    installation = raw_payload.get("installation") or {}
    issue_user = issue.get("user") or {}
    comment_user = comment.get("user") or {}

    flat: dict[str, Any] = {
        "delivery": delivery,
        "installation_id": installation.get("id"),
        "repo_owner": owner,
        "repo_name": repository.get("name"),
        "gh_repo_id": repository.get("id"),
        "default_branch": repository.get("default_branch"),
        "pr_number": issue.get("number"),
        "pr_author_login": issue_user.get("login"),
        "commenter_login": comment_user.get("login"),
        "author_association": comment.get("author_association"),
        "comment_id": comment.get("id"),
        "comment_body": comment.get("body"),
    }
    return IssueCommentTriggerInput.model_validate(flat)


def _slug_in_match(body: str, app_slug: str) -> bool:
    """True iff any ``@<slug> review`` token in ``body`` matches ``app_slug``."""
    if not body or not app_slug:
        return False
    target = app_slug.lower()
    for match in REVIEW_MENTION_RE.finditer(body):
        if match.group("slug").lower() == target:
            return True
    return False


def should_review_comment(body: str, app_slug: str) -> bool:
    """Case-insensitive ``@<app_slug> review`` match, anywhere in ``body``.

    The match tolerates extra punctuation / newlines between the
    mention and the word ``review`` (e.g. ``@reviewpr,\\nplease review``)
    because :data:`REVIEW_MENTION_RE` only requires whitespace between
    them. The word boundary on ``review`` prevents false positives
    like ``@reviewpr reviews``.
    """
    return _slug_in_match(body, app_slug)


def is_pr_comment(payload: dict[str, Any]) -> bool:
    """True iff the ``issue_comment`` event is on a pull request.

    GitHub's ``issue_comment`` event fires for both issues and pull
    requests. The discriminator is the presence of the
    ``pull_request`` key on the ``issue`` object — it is set when
    the parent is a PR and absent otherwise.
    """
    issue = payload.get("issue") or {}
    return issue.get("pull_request") is not None


def is_self_comment(payload: dict[str, Any], app_slug: str) -> bool:
    """True iff the commenter is the bot itself (case-insensitive).

    Skips self-mentions to avoid a feedback loop where the bot's
    own replies to a comment re-trigger the workflow.
    """
    if not app_slug:
        return False
    commenter = ((payload.get("comment") or {}).get("user") or {}).get("login")
    if not isinstance(commenter, str):
        return False
    return commenter.lower() == app_slug.lower()


def commenter_is_authorized(payload: dict[str, Any]) -> bool:
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


def classify_comment(
    payload: dict[str, Any],
    *,
    app_slug: str,
) -> ClassifyCommentResult:
    """Decide whether a comment should trigger a review.

    Sequential short-circuit — the first failing check wins and sets
    ``skip_reason``. Order is significant: cheap structural checks
    (action / is_pr) run first, then content checks (mention), then
    the network-independent authorization check last.

    Returns:
        :class:`ClassifyCommentResult` with ``should_proceed=True`` iff
        every check passed.
    """
    action = payload.get("action")
    if action != "created":
        return ClassifyCommentResult(should_proceed=False, skip_reason="not_created")

    if not is_pr_comment(payload):
        return ClassifyCommentResult(should_proceed=False, skip_reason="not_a_pr")

    if is_self_comment(payload, app_slug):
        return ClassifyCommentResult(should_proceed=False, skip_reason="self_comment")

    body = (payload.get("comment") or {}).get("body")
    body_str = body if isinstance(body, str) else ""
    if not should_review_comment(body_str, app_slug):
        return ClassifyCommentResult(should_proceed=False, skip_reason="missing_mention")

    if not commenter_is_authorized(payload):
        return ClassifyCommentResult(
            should_proceed=False, skip_reason="unauthorized_commenter"
        )

    return ClassifyCommentResult(should_proceed=True)


def _classify_pr_status(state: str | None, merged: bool) -> PRStatus:
    """Map a (state, merged) pair onto :class:`PRStatus`."""
    if state == "open":
        return PRStatus.OPEN
    if state == "closed":
        return PRStatus.MERGED if merged else PRStatus.CLOSED
    return PRStatus.OPEN


def build_review_workflow_input(
    *,
    trigger: IssueCommentTriggerInput,
    gh_pr_id: int,
    base_sha: str,
    head_sha: str,
    base_branch: str,
    head_branch: str,
    title: str,
    body: str,
    author: str,
    state: str,
    merged: bool,
    pr_size: PRSizeStats,
    user_id: str,
    llm_config: LLMConfig,
) -> ReviewWorkflowInput:
    """Translate a trigger input + fetched PR state into the inner review input.

    The inner :func:`app.services.review.workflow.review_workflow` only
    knows about :class:`ReviewWorkflowInput`; the trigger workflow
    builds one and dispatches it via
    :func:`app.services.pr_issue_comment.steps.dispatch_review.run_review_workflow`.

    All PR-side fields (``gh_pr_id``, ``base_sha``, ``head_sha``,
    ``base_branch``, ``head_branch``, ``title``, ``body``, ``author``,
    ``state``, ``merged``, ``pr_size``) come from
    :func:`app.services.pr_issue_comment.steps.fetch_pr_state.fetch_pr_state_step`
    — the comment payload does not carry them. ``default_branch`` is
    the exception: it is read straight off the payload's
    ``repository.default_branch`` via :class:`IssueCommentTriggerInput`.
    """
    return ReviewWorkflowInput(
        user_id=user_id,
        gh_repo_id=trigger.gh_repo_id,
        pr_id=gh_pr_id,
        pr_number=trigger.pr_number,
        branch=base_branch,
        default_branch=trigger.default_branch,
        base_sha=base_sha,
        head_sha=head_sha,
        head_branch=head_branch,
        author=author,
        body=body or "",
        title=title or "",
        status=_classify_pr_status(state, merged),
        trigger="comment",
        pr_size=pr_size,
        llm_config=llm_config,
        post_to_github=True,
        github_installation_id=trigger.installation_id,
    )


__all__ = [
    "REVIEW_MENTION_RE",
    "ValidationError",
    "WRITE_ASSOCIATIONS",
    "build_review_workflow_input",
    "classify_comment",
    "commenter_is_authorized",
    "is_pr_comment",
    "is_self_comment",
    "should_review_comment",
    "validate_comment_payload",
]
