"""Step: assemble the inner :class:`ReviewWorkflowInput`.

Pure data transformation. The trigger workflow calls this with the
typed :class:`IssueCommentTriggerInput`, the fetched
:class:`PRStateSnapshot`, the resolved user id, and the LLM
config. The result is the serialisable input the inner
``review_workflow`` already consumes.

The pure body lives in
:func:`app.services.pr_issue_comment.helpers.build_review_workflow_input`;
this module only re-exports it as a :func:`@DBOS.step` so the
trigger workflow can treat it like every other step.
"""

from __future__ import annotations

from dbos import DBOS

from app.core.llm import LLMConfig
from app.services.pr_issue_comment.helpers import build_review_workflow_input
from app.services.pr_issue_comment.types import (
    IssueCommentTriggerInput,
    PRStateSnapshot,
)
from app.services.review.workflow_types import ReviewWorkflowInput


@DBOS.step()
def build_review_input_step(
    *,
    trigger: IssueCommentTriggerInput,
    pr_state: PRStateSnapshot,
    user_id: str,
    llm_config: LLMConfig,
    diff_base_sha: str | None = None,
) -> ReviewWorkflowInput:
    """Durable DBOS step: build the inner :class:`ReviewWorkflowInput`.

    Pure function wrapped as a step so the trigger workflow can
    treat it uniformly with the other I/O boundaries. The step is
    DBOS-checkpointed but does not perform any I/O; it exists for
    symmetry and for any future pure logic we may want to add
    (e.g. PR title sanitization) without changing the trigger
    workflow's call shape.

    ``diff_base_sha`` is the incremental-re-review override from
    :func:`app.services.pr_issue_comment.helpers.effective_diff_base`;
    when ``None`` the inner workflow diffs from ``pr_state.base_sha``
    (first-review behaviour).
    """
    return build_review_workflow_input(
        trigger=trigger,
        gh_pr_id=pr_state.gh_pr_id,
        base_sha=pr_state.base_sha,
        head_sha=pr_state.head_sha,
        base_branch=pr_state.base_branch,
        head_branch=pr_state.head_branch,
        title=pr_state.title,
        body=pr_state.body,
        author=pr_state.author,
        state=pr_state.state,
        merged=pr_state.merged,
        pr_size=pr_state.pr_size,
        user_id=user_id,
        llm_config=llm_config,
        diff_base_sha=diff_base_sha,
    )


__all__ = ["build_review_input_step"]
