"""Review workflow package.

The refactored, convention-compliant review pipeline — built on the
refactored service layer (``agent`` / ``github`` / ``llm`` / ``sandbox``).
The webhook triggers dispatch it via :mod:`.triggers` (the edge
adapters wired into the github webhook sub-service's delegation
handlers).

Submodules:

- :mod:`.types`     — the contract: :class:`ReviewWorkflowCtx`
  (resolved LLM + sandbox environment) and :class:`ReviewWorkflowInput`
  (PR-specific trigger data), plus result projections, the usage
  envelopes, and the comment-trigger contract
  (:class:`CommentTriggerInput` / :class:`ClassifyCommentResult` /
  :class:`LastReviewSnapshot`). Ids are branded types from
  :mod:`app.utils.branded`.
- :mod:`.helpers`   — pure comment-trigger logic: payload validation,
  ``@<app_slug> review`` classification, and the incremental
  re-review diff-base decision.
- :mod:`.errors`    — error values (BaseModel, ``retryable`` flag +
  branded identity) returned by pure step functions, plus the raised
  step-exception wrappers used by the DBOS step edges.
- :mod:`.workflow`  — the :func:`reviewWorkflow` DBOS orchestrator and
  its pure helpers (workflow id, limits, input builder).
- :mod:`.triggers`  — the webhook edge adapters (``pull_request``
  ``opened`` + ``issue_comment`` ``created``) that resolve the run
  environment and dispatch :func:`reviewWorkflow`.
- :mod:`.steps`     — one file per I/O boundary: value-returning
  workers + DBOS edges.
- :file:`scripts/`   — in-sandbox files uploaded as bytes (never
  imported on the host): ``split_diff.py``.
"""

from __future__ import annotations

from app.workflows.review.errors import (
    AgentLaneError,
    CloneError,
    CloneTransientError,
    DiffSplitError,
    DiffSplitSetupError,
    DiffUnavailableError,
    ExtractionError,
    LifecycleUpdateError,
    PersistError,
    PostReviewError,
    RepoGetError,
    ReviewAgentsError,
    ReviewStepError,
    ReviewStepFailure,
    SandboxConnectError,
    SandboxCreateError,
    TransientReviewStepFailure,
    UpsertPRError,
    extractRetryAfterSeconds,
    isLlmRetryError,
    isRetryableStatusCode,
    shouldRetry,
)
from app.workflows.review.types import (
    InputTokenDetails,
    PRSizeStats,
    PostReviewResult,
    RepoSnapshot,
    ReviewLimits,
    ReviewRunResult,
    ReviewWorkflowCtx,
    ReviewWorkflowInput,
    SplitDiffResult,
    TotalUsages,
    TotalUsagesPerPR,
)
from app.workflows.review.workflow import (
    buildReviewWorkflowInput,
    computeReviewLimits,
    createReviewWorkflowId,
    reviewWorkflow,
)

__all__ = [
    "AgentLaneError",
    "CloneError",
    "CloneTransientError",
    "DiffSplitError",
    "DiffSplitSetupError",
    "DiffUnavailableError",
    "ExtractionError",
    "InputTokenDetails",
    "LifecycleUpdateError",
    "PRSizeStats",
    "PersistError",
    "PostReviewError",
    "PostReviewResult",
    "RepoGetError",
    "RepoSnapshot",
    "ReviewAgentsError",
    "ReviewLimits",
    "ReviewRunResult",
    "ReviewStepError",
    "ReviewStepFailure",
    "ReviewWorkflowCtx",
    "ReviewWorkflowInput",
    "SandboxConnectError",
    "SandboxCreateError",
    "SplitDiffResult",
    "TotalUsages",
    "TotalUsagesPerPR",
    "TransientReviewStepFailure",
    "UpsertPRError",
    "buildReviewWorkflowInput",
    "computeReviewLimits",
    "createReviewWorkflowId",
    "extractRetryAfterSeconds",
    "isLlmRetryError",
    "isRetryableStatusCode",
    "reviewWorkflow",
    "shouldRetry",
]