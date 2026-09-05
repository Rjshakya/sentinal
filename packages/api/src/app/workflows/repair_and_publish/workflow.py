"""Repair-and-publish durable workflow.

This module owns the top-level :func:`repairAndPublishReviewWorkflow`
DBOS workflow that pushes a saved-but-unpublished review to GitHub,
plus its pure workflow helper :func:`repairAndPublishWorkflowId`.

Flow — exact parity with the review workflow's sandbox sequence:

1. :func:`app.workflows.repair_and_publish.steps.check_unpublished.checkUnpublishedReviewExist`
   — ``None`` when no unpublished review exists (no review row, no
   summary, or the summary already carries a ``github_commitId``):
   the workflow completes without posting.
2. :func:`app.workflows.review.steps.create_sandbox.createSandboxStep`
   — the per-run ephemeral sandbox (exported from the review package).
3. :func:`app.workflows.review.steps.clone_repo.cloneRepoStep` + the
   review pipeline's
   :func:`app.workflows.review.steps.fetch_diff.fetchDiffStep` — the
   diff is produced from a git clone inside the sandbox
   (``git diff base...head``), not the GitHub API: the API refuses to
   render the ``.diff`` media type for PRs whose diff exceeds 20,000
   lines (``406 too_large``), while git has no line cap.
4. :func:`app.workflows.repair_and_publish.steps.delete_repo.deleteRepoStep`
   — remove the clone: only the diff artefacts at ``{diff_dir}/`` are
   needed from here on (best-effort cleanup).
5. :func:`app.workflows.review.steps.split_diff.splitDiffStep` — the
   split script (exported from the review package) turns the diff into
   ``overview.md`` + ``splitted_diffs/`` chunks.
6. :func:`app.workflows.repair_and_publish.steps.repair_and_publish.repairAndPublishToGithub`
   — the deepagent harness: the saved summary + comments are final, the
   agent fixes only the anchors GitHub rejected and posts the whole
   review — summary + verdict + comments — as one atomic review through
   the ``publish_to_github`` tool (max 3 calls).
7. :func:`app.workflows.repair_and_publish.steps.save_published.savePublishedReview`
   — writes the posted ``github_commitId`` onto the ``review`` /
   ``review_summaries`` rows, keeps the posted rows (``commitId``
   written explicitly), and deletes the rows that were never posted.

The sandbox is destroyed in the ``finally`` via
:func:`app.workflows.review.steps.kill_sandbox.killSandboxStep`, so a
raising step never leaks a paused sandbox.
"""

from __future__ import annotations

import logging

from dbos import DBOS, SetWorkflowID
from pydantic import BaseModel

from app.utils.branded import ReviewRowId
from app.workflows.repair_and_publish.errors import (
    CheckError,
    RepairPublishStepFailure,
)
from app.workflows.repair_and_publish.helpers import createRepairAndPublishWorkflowId
from app.workflows.repair_and_publish.steps.check_unpublished import (
    checkUnpublishedReviewExist,
)
from app.workflows.repair_and_publish.steps.delete_repo import deleteRepoStep
from app.workflows.repair_and_publish.steps.repair_and_publish import (
    repairAndPublishToGithub,
)
from app.workflows.repair_and_publish.steps.save_published import (
    savePublishedReview,
    savePublishedReviewStep,
)
from app.workflows.repair_and_publish.types import (
    RepairAndPublishResult,
    RepairAndPublishWorkflowCtx,
    RepairAndPublishWorkflowInput,
)
from app.workflows.review.steps.clone_repo import cloneRepoStep
from app.workflows.review.steps.create_sandbox import createSandboxStep
from app.workflows.review.steps.fetch_diff import fetchDiffStep
from app.workflows.review.steps.kill_sandbox import killSandboxStep
from app.workflows.review.steps.split_diff import splitDiffStep
from traceloop.sdk.decorators import workflow as traceloop_workflow
from traceloop.sdk import Traceloop

from app.services.llm.types import LLMCtx
from app.services.sandbox.types import SandboxCtx
from app.utils.branded import CommitId, PRNumber

log = logging.getLogger(__name__)


@traceloop_workflow(name="repair_and_publish_workflow")
@DBOS.workflow()
async def repairAndPublishReviewWorkflow(
    ctx: RepairAndPublishWorkflowCtx,
    input: RepairAndPublishWorkflowInput,
) -> RepairAndPublishResult:
    """Repair and publish a saved-but-unpublished review to GitHub.

    The summary + comments stay as the pipeline produced them; the
    repair agent fixes only the anchors GitHub rejected, and the
    workflow saves the posted ids back onto the local rows.
    """

    workflowId: str = DBOS.workflow_id or "<no-workflow-id>"

    Traceloop.set_association_properties(
        {
            "commitId": input.commitId,
            "workflow_id": workflowId,
        }
    )

    log.info(
        "repair_and_publish: starting workflow: commitId=%s",
        input.commitId,
    )

    unpublished = await checkUnpublishedReviewExist(commitId=input.commitId)

    if unpublished is None:
        log.info(
            "repair_and_publish: no unpublished review, skipping: commitId=%s",
            input.commitId,
        )
        return RepairAndPublishResult(posted=False, reason="skipped")

    base_sha = unpublished.baseSha
    if base_sha is None:
        raise RepairPublishStepFailure(
            CheckError(
                message=(
                    "review row has no base_sha; cannot produce the diff "
                    f"(review_id={unpublished.reviewId!r})"
                ),
                reviewId=unpublished.reviewId,
            )
        )

    sandbox_ctx = await createSandboxStep(ctx.sandboxCtx)
    try:
        await cloneRepoStep(
            sandboxCtx=sandbox_ctx,
            userId=unpublished.userId,
            repoId=unpublished.repoId,
            repoOwner=unpublished.repoOwner,
            repoName=unpublished.repoName,
            prNumber=unpublished.prNumber,
            githubInstallationId=unpublished.installationId,
        )

        diff = await fetchDiffStep(
            sandboxCtx=sandbox_ctx,
            repoId=unpublished.repoId,
            repoName=unpublished.repoName,
            prNumber=unpublished.prNumber,
            headSha=unpublished.commitId,
            baseSha=base_sha,
            diffBaseSha=None,
        )
        diff_dir = diff.diffFile.rsplit("/", 1)[0]

        await deleteRepoStep(
            sandboxCtx=sandbox_ctx,
            repoName=unpublished.repoName,
        )

        await splitDiffStep(
            sandboxCtx=sandbox_ctx,
            repoId=unpublished.repoId,
            prNumber=unpublished.prNumber,
            headSha=unpublished.commitId,
        )

        published = await repairAndPublishToGithub(
            ctx=ctx,
            unpublished=unpublished,
            sandboxCtx=sandbox_ctx,
            diffDir=diff_dir,
        )
    finally:
        await killSandboxStep(sandboxCtx=sandbox_ctx)

    if published is None:
        log.warning(
            "repair_and_publish: agent published nothing: commitId=%s " "pr_number=%s",
            input.commitId,
            unpublished.prNumber,
        )
        return RepairAndPublishResult(
            posted=False,
            reason="post_failed",
            error="repair agent finished without publishing",
        )

    await savePublishedReviewStep(
        unpublished=unpublished,
        published=published,
    )

    log.info(
        "repair_and_publish: stopping workflow: commitId=%s github_commitId=%s "
        "posted=%d left=%d attempts=%d",
        input.commitId,
        published.githubReviewId,
        len(published.postedComments),
        len(published.leftComments),
        published.attempts,
    )
    return RepairAndPublishResult(
        posted=True,
        reason="posted",
        githubReviewId=published.githubReviewId,
        commentCount=len(published.postedComments),
        attempts=published.attempts,
    )


class DispatchRepairAndPublishWorkflowInput(BaseModel):
    prNumber: PRNumber
    commitId: CommitId
    llmCtx: LLMCtx
    sandboxCtx: SandboxCtx


async def dispatchRepairAndPublishWorkflow(
    input: DispatchRepairAndPublishWorkflowInput,
):

    workflowId = createRepairAndPublishWorkflowId(
        prNumber=input.prNumber, commitId=input.commitId
    )
    with SetWorkflowID(workflowId):
        await DBOS.start_workflow_async(
            repairAndPublishReviewWorkflow,
            ctx=RepairAndPublishWorkflowCtx(
                llmCtx=input.llmCtx, sandboxCtx=input.sandboxCtx
            ),
            input=RepairAndPublishWorkflowInput(commitId=input.commitId),
        )

    return workflowId


__all__ = [
    "repairAndPublishReviewWorkflow",
]
