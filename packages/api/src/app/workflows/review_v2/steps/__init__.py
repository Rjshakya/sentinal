"""V2 review workflow steps: one file per I/O boundary.

Every step file follows the service conventions:

- a **value-returning worker** (explicit inputs — ctxs, sessions,
  handles — returning ``T | ErrorValue``; no logging, no raising), and
- a **durable edge** (``@durable_step`` wrapper in
  :mod:`app.workflows.durable`) that checkpoints the worker with the
  SDK retry strategy and raises
  :class:`app.workflows.review_v2.errors.TransientReviewStepFailure`
  (retryable) or :class:`app.workflows.review_v2.errors.ReviewStepFailure`
  (business outcome).

The sandbox handle never crosses a step boundary: steps receive the
serializable :class:`app.services.sandbox.types.SandboxCtx` and
reconnect by id via :func:`app.workflows.review_v2.steps._helpers.connectSandbox`.

- Infra steps (``create_sandbox``, ``clone`` is v2-native,
  ``fetch_diff``, ``split_diff``, ``persist``, ``post_review``,
  ``review_lifecycle``, ``extract_result``) — the shared pipeline
  plumbing.
- :mod:`.list_chunks` — inventory the ``splitted_diffs/`` chunks
  (the host-side diff truth).
- :mod:`.clone_repo_v2` — v2-native clone: default-branch clone +
  PR-ref fetch + detached head checkout in one atomic script
  (fail-closed on checkout refusal).
- :mod:`.invoke_planner` — run the planning agent (it submits via
  the ``submit_plan`` tool) + read the structured
  :class:`PlannerContext` back from ``plan.json``.
- :mod:`.invoke_file` — run one per-file review agent.
- :mod:`.synthesize_summary` — synthesize the walkthrough summary
  (info + ASCII flow tree + important files) from validated run data.
- :mod:`.combine` — pure join / merge helpers (trivial filter,
  context join, report concat, batching, outcome combining).
"""

from app.workflows.review_v2.steps.clone_repo_v2 import (
    CloneV2Result,
    cloneRepoV2,
    cloneRepoV2Step,
    parseCloneV2Result,
)
from app.workflows.review_v2.steps.combine import (
    BuiltJobs,
    CombinedReview,
    buildFileReviewJobs,
    chunkedJobs,
    coerceFileLaneError,
    combineReviewResults,
    combineV2Reports,
    concatFileReports,
    isTrivialFile,
    verdictFor,
)
from app.workflows.review_v2.steps.create_sandbox import (
    createSandbox,
    createSandboxStep,
)
from app.workflows.review_v2.steps.extract_result import (
    buildExtractorLlmCtx,
    extractCommentsStep,
    extractSummaryStep,
)
from app.workflows.review_v2.steps.fetch_diff import fetchDiff, fetchDiffStep
from app.workflows.review_v2.steps.get_repo import getRepo, getRepoTx
from app.workflows.review_v2.steps.invoke_file import (
    FileStepOutcome,
    invokeFileReviewStep,
)
from app.workflows.review_v2.steps.invoke_planner import (
    PlannerStepOutcome,
    getPlanStep,
    invokePlannerStep,
    parsePlanText,
    readPlanText,
)
from app.workflows.review_v2.steps.kill_sandbox import killSandboxStep
from app.workflows.review_v2.steps.list_chunks import (
    connectV2Sandbox,
    listChunkFiles,
    listChunkFilesStep,
    parseChunkHeaders,
)
from app.workflows.review_v2.steps.persist import (
    persistCodeComments,
    persistCodeCommentsTx,
    persistReviewSummary,
    persistReviewSummaryTx,
    persistReviewUsage,
    persistReviewUsageTx,
    sumTotalUsages,
)
from app.workflows.review_v2.steps.post_review import (
    buildPostReviewDraft,
    postReviewStep,
    updatePostBacklinks,
    updatePostBacklinksTx,
)
from app.workflows.review_v2.steps.review_lifecycle import (
    buildErrorContext,
    markReviewErrored,
    markReviewErroredStep,
    markReviewRunning,
    markReviewRunningStep,
    markReviewStopped,
    markReviewStoppedStep,
)
from app.workflows.review_v2.steps.split_diff import (
    parseSplitSummary,
    splitDiff,
    splitDiffStep,
)
from app.workflows.review_v2.steps.synthesize_summary import synthesizeSummaryStep
from app.workflows.review_v2.steps.upsert_pr import (
    upsertPullRequest,
    upsertPullRequestTx,
)

__all__ = [
    "BuiltJobs",
    "CloneV2Result",
    "CombinedReview",
    "FileStepOutcome",
    "PlannerStepOutcome",
    "buildErrorContext",
    "buildExtractorLlmCtx",
    "buildFileReviewJobs",
    "buildPostReviewDraft",
    "chunkedJobs",
    "cloneRepoV2",
    "cloneRepoV2Step",
    "coerceFileLaneError",
    "combineReviewResults",
    "combineV2Reports",
    "concatFileReports",
    "connectV2Sandbox",
    "createSandbox",
    "createSandboxStep",
    "extractCommentsStep",
    "extractSummaryStep",
    "fetchDiff",
    "fetchDiffStep",
    "getPlanStep",
    "getRepo",
    "getRepoTx",
    "invokeFileReviewStep",
    "invokePlannerStep",
    "isTrivialFile",
    "killSandboxStep",
    "listChunkFiles",
    "listChunkFilesStep",
    "markReviewErrored",
    "markReviewErroredStep",
    "markReviewRunning",
    "markReviewRunningStep",
    "markReviewStopped",
    "markReviewStoppedStep",
    "parseChunkHeaders",
    "parseCloneV2Result",
    "parsePlanText",
    "parseSplitSummary",
    "persistCodeComments",
    "persistCodeCommentsTx",
    "persistReviewSummary",
    "persistReviewSummaryTx",
    "persistReviewUsage",
    "persistReviewUsageTx",
    "postReviewStep",
    "readPlanText",
    "splitDiff",
    "splitDiffStep",
    "sumTotalUsages",
    "synthesizeSummaryStep",
    "updatePostBacklinks",
    "updatePostBacklinksTx",
    "upsertPullRequest",
    "upsertPullRequestTx",
    "verdictFor",
]
