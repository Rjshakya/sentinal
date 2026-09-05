"""Review workflow steps: one file per I/O boundary.

Every step file follows the new service conventions:

- a **value-returning worker** (explicit inputs — ctxs, sessions,
  handles — returning ``T | ErrorValue``; no logging, no DBOS, no
  raising), and
- a **DBOS edge** (``@DBOS.step`` / ``@dbos_datasource.transaction()``)
  that logs, discriminates the error value with ``isinstance``, and
  raises :class:`app.workflows.review.errors.TransientReviewStepFailure`
  (retryable) or :class:`app.workflows.review.errors.ReviewStepFailure`
  (business outcome).

The sandbox handle never crosses a step boundary: steps receive the
serializable :class:`app.services.sandbox.types.SandboxCtx` and
reconnect by id via :func:`app.workflows.review.steps._helpers.connectSandbox`.
"""

from __future__ import annotations

from app.workflows.review.steps.clone_repo import cloneRepoStep
from app.workflows.review.steps.create_sandbox import createSandbox, createSandboxStep
from app.workflows.review.steps.extract_result import (
    buildExtractorLlmCtx,
    extractCommentsStep,
    extractSummaryStep,
)
from app.workflows.review.steps.fetch_diff import fetchDiff, fetchDiffStep
from app.workflows.review.steps.get_repo import getRepo, getRepoTx
from app.workflows.review.steps.invoke_agent import (
    combineLaneOutcomes,
    invokeAgentStep,
    runExtractorLanes,
)
from app.workflows.review.steps.kill_sandbox import killSandboxStep
from app.workflows.review.steps.persist import (
    persistCodeComments,
    persistCodeCommentsTx,
    persistReviewSummary,
    persistReviewSummaryTx,
    persistReviewUsage,
    persistReviewUsageTx,
    sumTotalUsages,
)
from app.workflows.review.steps.post_review import (
    buildPostReviewDraft,
    postReviewStep,
    updatePostBacklinks,
    updatePostBacklinksTx,
)
from app.workflows.review.steps.review_lifecycle import (
    buildErrorContext,
    markReviewErrored,
    markReviewErroredStep,
    markReviewRunning,
    markReviewRunningStep,
    markReviewStopped,
    markReviewStoppedStep,
)
from app.workflows.review.steps.split_diff import parseSplitSummary, splitDiff, splitDiffStep
from app.workflows.review.steps.upsert_pr import upsertPullRequest, upsertPullRequestTx

__all__ = [
    "buildErrorContext",
    "buildExtractorLlmCtx",
    "buildPostReviewDraft",
    "cloneRepoStep",
    "combineLaneOutcomes",
    "createSandbox",
    "createSandboxStep",
    "extractCommentsStep",
    "extractSummaryStep",
    "fetchDiff",
    "fetchDiffStep",
    "getRepo",
    "getRepoTx",
    "invokeAgentStep",
    "killSandboxStep",
    "markReviewErrored",
    "markReviewErroredStep",
    "markReviewRunning",
    "markReviewRunningStep",
    "markReviewStopped",
    "markReviewStoppedStep",
    "parseSplitSummary",
    "persistCodeComments",
    "persistCodeCommentsTx",
    "persistReviewSummary",
    "persistReviewSummaryTx",
    "persistReviewUsage",
    "persistReviewUsageTx",
    "postReviewStep",
    "runExtractorLanes",
    "splitDiff",
    "splitDiffStep",
    "sumTotalUsages",
    "updatePostBacklinks",
    "updatePostBacklinksTx",
    "upsertPullRequest",
    "upsertPullRequestTx",
]