"""Dispatch the inner ``review_workflow`` for a comment trigger.

The trigger workflow is intentionally a thin orchestrator. After all
the pre-work (validation, classification, ID resolution, head-SHA
fetch, ack reaction, LLM resolution, input building) it hands the
final :class:`ReviewWorkflowInput` off to
:func:`run_review_workflow`, which starts the inner
``review_workflow`` with the deterministic
``review:{local_repo_id}:{pr_number}:{head_sha[:7]}`` workflow id.

The deterministic id is the idempotency key: a second comment on the
same head SHA, or a ``pull_request opened`` + comment arriving for
the same head SHA, dedupe to the same inner review workflow and
the inner review returns the cached result.

Note: this is **not** a :func:`@DBOS.step`. DBOS forbids starting a
child workflow from inside a step (:meth:`DBOSContext.create_start_workflow_child`
asserts the current context ``is_workflow()`` — ``# Not in a step``),
so the function is called directly from the
:func:`trigger_issue_comment_workflow` workflow body, exactly like
:func:`app.services.review.workflow.review_workflow` starts
:func:`app.services.github.workflow.post_review_to_github_workflow`.

Replay safety: on crash-replay the workflow body re-executes this
call, but DBOS records child-workflow starts keyed on the parent's
function id, and the inner workflow id is deterministic via
:class:`SetWorkflowID`, so a re-enqueue resolves to the already
recorded child workflow instead of starting a second run.
"""

from __future__ import annotations

import logging

from dbos import DBOS, SetWorkflowID

from app.services.review.helpers import create_review_workflow_id
from app.services.review.workflow import review_workflow
from app.services.review.workflow_types import ReviewWorkflowInput

log = logging.getLogger(__name__)


async def run_review_workflow(
    workflow_input: ReviewWorkflowInput,
    *,
    repo_id: str,
    pr_number: int,
    head_sha: str,
) -> str:
    """Enqueue the inner ``review_workflow`` and return its workflow id.

    Called from the ``trigger_issue_comment_workflow`` body (not as a
    DBOS step — starting a child workflow from a step is an
    ``AssertionError`` in DBOS). Wraps
    :func:`DBOS.start_workflow_async` with a :class:`SetWorkflowID` so
    duplicate triggers on the same head SHA are deduped. The returned
    id (the same one used as the idempotency key) is recorded in the
    :class:`TriggerRunResult`. The inner review runs in the background;
    this function does not wait for it to complete.
    """
    workflow_id = create_review_workflow_id(
        repo_id=repo_id,
        pr_number=pr_number,
        head_sha=head_sha,
    )

    log.info(
        "pr_issue_comment.run_review_workflow: starting "
        "review_workflow from issue comment: workflow_id=%s gh_repo_id=%s pr_number=%s "
        "head_sha=%s post_to_github=%s",
        workflow_id,
        workflow_input.gh_repo_id,
        pr_number,
        head_sha,
        workflow_input.post_to_github,
    )

    with SetWorkflowID(workflow_id):
        await DBOS.start_workflow_async(review_workflow, workflow_input)

    return workflow_id


__all__ = ["run_review_workflow"]
