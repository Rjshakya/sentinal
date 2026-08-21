"""DBOS workflow: ``trigger_issue_comment_workflow``.

The trigger workflow is the durable, retryable owner of every
``issue_comment`` pre-work step. The router enqueues one
instance per GitHub delivery; the workflow runs the
classify-then-dispatch sequence and finally starts the inner
``review_workflow`` (which lives in
:mod:`app.services.review.workflow` and is unchanged).

Workflow id: ``trigger_issue_comment:{comment_id}`` (set by the
router via :class:`SetWorkflowID`). DBOS dedupes redelivered
GitHub webhooks for the same comment.

Inner workflow id: ``review:{local_repo_id}:{pr_number}:{head_sha[:7]}``
(computed by
:func:`app.services.pr_issue_comment.steps.dispatch_review.run_review_workflow`).
Same head SHA across a ``pull_request opened`` and a comment
trigger dedupes to a single review run.

Design notes:

- The workflow is a straight-line sequence of :func:`@DBOS.step`
  calls. Each step raises on transient failure; DBOS retries per
  the step's ``should_retry`` policy. Plain business outcomes
  (missing installation, unauthorized commenter, etc.) return
  :class:`TriggerRunResult` with a ``skip_reason`` and do not
  raise.
- Pure helpers (validate / classify) are called in the workflow
  body, not as steps. They have no I/O to checkpoint.
- The 👀 reaction step is best-effort: it never raises, so its
  failure cannot block the review dispatch.
- On a successful inner review dispatch the result carries the
  inner workflow id. On any skip reason the inner workflow id is
  ``None``.
"""

from __future__ import annotations

import logging
from typing import Any

from dbos import DBOS
from pydantic import ValidationError

from app.core.config import settings
from app.services.pr_issue_comment.helpers import (
    classify_comment,
    effective_diff_base,
    validate_comment_payload,
)
from app.services.pr_issue_comment.steps import (
    add_eyes_reaction_step,
    build_review_input_step,
    fetch_pr_state_step,
    resolve_installation_step,
    resolve_last_review_step,
    resolve_llm_config_step,
    resolve_repo_id_step,
)
from app.services.pr_issue_comment.steps.dispatch_review import run_review_workflow
from app.services.pr_issue_comment.types import TriggerRunResult

log = logging.getLogger(__name__)


def _skip(trigger_id: str, reason: str) -> TriggerRunResult:
    """Build a ``skip_reason`` result with no inner workflow id."""
    log.info(
        "trigger_issue_comment_workflow: skip: trigger_id=%s reason=%s",
        trigger_id,
        reason,
    )
    return TriggerRunResult(
        trigger_workflow_id=trigger_id,
        review_workflow_id=None,
        dispatched=False,
        skip_reason=reason,
    )


@DBOS.workflow()
async def trigger_issue_comment_workflow(
    raw_payload: dict[str, Any],
    delivery: str,
    app_slug: str,
) -> TriggerRunResult:
    """Durable workflow: turn a comment-mention into a review dispatch.

    Sequence:

    1. **Validate** — project the raw payload onto
       :class:`IssueCommentTriggerInput`. Failure -> ``malformed_payload``.
    2. **Classify** — action / is_pr / is_self / has_mention /
       is_authorized. Any failure -> the corresponding ``skip_reason``.
    3. **Resolve installation** — find the local ``Installation`` row.
       Missing or unattributed -> ``unowned_installation``.
    4. **Resolve repo** — find the local ``Repo`` id. Missing ->
       ``repo_not_indexed``.
    5. **Env gate** — ``llm_configured`` and ``sandbox_configured``.
       Failure -> ``review_not_configured``.
6. **Fetch PR state** — ``GET /repos/{owner}/{repo}/pulls/{pr}``.
       Retried by DBOS on transient GitHub failures. On persistent
       failure the workflow converts the error to ``pr_fetch_failed``.
    7. **Resolve last review** — load the latest successful ``review``
       row for the PR. When its head differs from the fetched head,
       the inner review becomes an **incremental re-review**: the
       git-diff base is the last reviewed head, so only the commits
       pushed since the previous review are diffed.
    8. **Ack reaction** — best-effort 👀 on the comment.
    9. **Resolve LLM config** — per-user, with env fallback.
    10. **Build review input** — assemble the inner
        :class:`ReviewWorkflowInput`.
    11. **Dispatch review** — enqueue the inner ``review_workflow``
        with the deterministic id.

    Returns:
        A :class:`TriggerRunResult`. ``dispatched=True`` carries the
        inner ``review_workflow`` id; ``dispatched=False`` carries the
        ``skip_reason`` that explains why no review was enqueued.
    """
    trigger_id: str = DBOS.workflow_id or "unknown"

    try:
        trigger_input = validate_comment_payload(raw_payload, delivery=delivery)
    except ValidationError:
        return _skip(trigger_id, "malformed_payload")

    cls = classify_comment(raw_payload, app_slug=app_slug)

    if not cls.should_proceed:
        return _skip(trigger_id, cls.skip_reason or "unknown")

    installation = await resolve_installation_step(trigger_input.installation_id)

    if installation is None or installation.user_id is None:
        return _skip(trigger_id, "unowned_installation")

    repo_id = await resolve_repo_id_step(trigger_input.gh_repo_id)

    if repo_id is None:
        return _skip(trigger_id, "repo_not_indexed")

    if not settings.llm_configured or not settings.sandbox_configured:
        log.warning(
            "trigger_issue_comment_workflow: env not configured: "
            "trigger_id=%s llm_configured=%s sandbox_configured=%s",
            trigger_id,
            settings.llm_configured,
            settings.sandbox_configured,
        )
        return _skip(trigger_id, "review_not_configured")

    # fetch pr stata (get full details for pr)

    try:
        pr_state = await fetch_pr_state_step(
            trigger_input.installation_id,
            owner=trigger_input.repo_owner,
            repo=trigger_input.repo_name,
            pr_number=trigger_input.pr_number,
        )
    except Exception as exc:  # PRFetchError is the only expected class.
        log.warning(
            "trigger_issue_comment_workflow: fetch_pr_state_step failed: "
            "trigger_id=%s cause=%s: %s",
            trigger_id,
            type(exc).__name__,
            exc,
        )
        return _skip(trigger_id, "pr_fetch_failed")

    last_review = await resolve_last_review_step(
        repo_id=repo_id,
        pr_number=trigger_input.pr_number,
    )

    diff_base_sha = effective_diff_base(
        api_base_sha=pr_state.base_sha,
        api_head_sha=pr_state.head_sha,
        last_review=last_review,
    )
    if diff_base_sha is not None:
        log.info(
            "trigger_issue_comment_workflow: incremental re-review: "
            "trigger_id=%s pr_number=%s diff_base_sha=%s head_sha=%s",
            trigger_id,
            trigger_input.pr_number,
            diff_base_sha,
            pr_state.head_sha,
        )

    await add_eyes_reaction_step(
        trigger_input.installation_id,
        owner=trigger_input.repo_owner,
        repo=trigger_input.repo_name,
        comment_id=trigger_input.comment_id,
    )

    llm_config = await resolve_llm_config_step(installation.user_id)

    review_input = build_review_input_step(
        trigger=trigger_input,
        pr_state=pr_state,
        user_id=installation.user_id,
        llm_config=llm_config,
        diff_base_sha=diff_base_sha,
    )

    review_workflow_id = await run_review_workflow(
        review_input,
        repo_id=repo_id,
        pr_number=trigger_input.pr_number,
        head_sha=pr_state.head_sha,
    )

    log.info(
        "trigger_issue_comment_workflow: dispatched: trigger_id=%s "
        "review_workflow_id=%s gh_repo_id=%s pr_number=%s head_sha=%s",
        trigger_id,
        review_workflow_id,
        trigger_input.gh_repo_id,
        trigger_input.pr_number,
        pr_state.head_sha,
    )

    return TriggerRunResult(
        trigger_workflow_id=trigger_id,
        review_workflow_id=review_workflow_id,
        dispatched=True,
    )


__all__ = ["trigger_issue_comment_workflow"]
