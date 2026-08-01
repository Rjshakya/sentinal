"""Step: dispatch the inner ``review_workflow`` for a comment trigger.

The trigger workflow is intentionally a thin orchestrator. After all
the pre-work (validation, classification, ID resolution, head-SHA
fetch, ack reaction, LLM resolution, input building) it hands the
final :class:`ReviewWorkflowInput` off to
:func:`dispatch_review_workflow_step`, which starts the inner
``review_workflow`` with the deterministic
``review:{local_repo_id}:{pr_number}:{head_sha[:7]}`` workflow id.

The deterministic id is the idempotency key: a second comment on the
same head SHA, or a ``pull_request opened`` + comment arriving for
the same head SHA, dedupe to the same inner review workflow and
the inner review returns the cached result.
"""

from __future__ import annotations

import logging

from dbos import DBOS, SetWorkflowID

from app.services.review.helpers import create_review_workflow_id
from app.services.review.workflow import review_workflow
from app.services.review.workflow_types import ReviewWorkflowInput

log = logging.getLogger(__name__)


@DBOS.step()
async def dispatch_review_workflow_step(
    workflow_input: ReviewWorkflowInput,
    *,
    repo_id: str,
    pr_number: int,
    head_sha: str,
) -> str:
    """Durable DBOS step: enqueue the inner ``review_workflow``.

    Wraps :func:`DBOS.start_workflow_async` with a
    :class:`SetWorkflowID` so duplicate triggers on the same head
    SHA are deduped. The step returns the inner workflow id (the
    same one used as the idempotency key) so the trigger workflow
    can record it in the :class:`TriggerRunResult`.

    The step awaits the coroutine that ``start_workflow_async``
    returns so DBOS can checkpoint the enqueue before the step
    returns. The inner review runs in the background.
    """
    workflow_id = create_review_workflow_id(
        repo_id=repo_id,
        pr_number=pr_number,
        head_sha=head_sha,
    )

    log.info(
        "pr_issue_comment.dispatch_review_workflow_step: starting "
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


__all__ = ["dispatch_review_workflow_step"]
