"""Pydantic types for the ``issue_comment`` trigger pipeline.

These models cross the DBOS workflow / step boundary, so they are
plain ``BaseModel`` subclasses with ``frozen=True`` (no SQLModel
ORM, no ``date`` magic). Each one corresponds to a single concern:

- :class:`IssueCommentTriggerInput` — flat, typed view of the
  ``issue_comment`` webhook payload. The trigger workflow projects the
  raw JSON onto this model once, then carries the typed view through
  every step.

- :class:`ClassifyCommentResult` — the output of the pure
  :func:`app.services.pr_issue_comment.helpers.classify_comment`
  helper. Encodes the first failing early-exit check as
  ``skip_reason`` so the workflow can return a
  :class:`TriggerRunResult` without raising.

- :class:`TriggerRunResult` — what
  :func:`app.services.pr_issue_comment.workflow.trigger_issue_comment_workflow`
  returns to the router. Carries the trigger workflow id (for
  observability) and, on a successful dispatch, the inner
  ``review_workflow`` id.

- :class:`InstallationSnapshot` — serialisable subset of
  :class:`app.models.installation.Installation`, returned by
  :func:`app.services.pr_issue_comment.steps.resolve_installation.resolve_installation_step`.
  DBOS cannot persist SQLModel ORM rows across a step boundary, so the
  step returns this Pydantic snapshot instead.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class IssueCommentTriggerInput(BaseModel):
    """Flat, typed view of a verified ``issue_comment`` payload.

    Every field is required. The trigger workflow raises a
    ``malformed_payload`` skip when the raw webhook does not satisfy
    the pydantic schema.
    """

    model_config = ConfigDict(frozen=True)

    delivery: str
    installation_id: int
    repo_owner: str
    repo_name: str
    gh_repo_id: int
    default_branch: str | None = None
    pr_number: int
    pr_author_login: str
    commenter_login: str
    author_association: str
    comment_id: int
    comment_body: str


class ClassifyCommentResult(BaseModel):
    """Outcome of the pure classification helper.

    ``should_proceed`` is ``True`` iff every check (action / is_pr /
    is_self / has_mention / is_authorized) passed. The first failing
    check sets ``skip_reason`` to a stable string the router can log.
    """

    model_config = ConfigDict(frozen=True)

    should_proceed: bool
    skip_reason: str | None = None


class TriggerRunResult(BaseModel):
    """What the ``trigger_issue_comment_workflow`` returns.

    Either ``dispatched=True`` and ``review_workflow_id`` populated, or
    ``dispatched=False`` and ``skip_reason`` populated. ``review_workflow_id``
    is the deterministic id of the inner review workflow
    (``review:{local_repo_id}:{pr_number}:{head_sha[:7]}``).
    """

    model_config = ConfigDict(frozen=True)

    trigger_workflow_id: str
    review_workflow_id: str | None = None
    dispatched: bool
    skip_reason: str | None = None


class InstallationSnapshot(BaseModel):
    """Serializable subset of :class:`app.models.installation.Installation`.

    ``user_id`` is the local WorkOS user that owns the installation;
    it is ``None`` for orphan installations the setup callback has
    not yet attributed to a user.
    """

    model_config = ConfigDict(frozen=True)

    id: str
    account_login: str
    user_id: str | None = None


class PRStateSnapshot(BaseModel):
    """Serializable view of a pull request fetched via the GitHub REST API.

    Carries every field the inner
    :func:`app.services.review.workflow.review_workflow` needs that the
    ``issue_comment`` payload does not provide. Returned by
    :func:`app.services.pr_issue_comment.steps.fetch_pr_state.fetch_pr_state_step`
    so the trigger workflow can build a complete
    :class:`app.services.review.workflow_types.ReviewWorkflowInput`
    without a second API call.
    """

    model_config = ConfigDict(frozen=True)

    gh_pr_id: int
    base_sha: str
    head_sha: str
    base_branch: str
    head_branch: str
    title: str
    body: str
    author: str
    state: str
    merged: bool


__all__ = [
    "ClassifyCommentResult",
    "InstallationSnapshot",
    "IssueCommentTriggerInput",
    "PRStateSnapshot",
    "TriggerRunResult",
]
