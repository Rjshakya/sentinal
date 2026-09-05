"""Repair-and-publish workflow package.

Recovers reviews that completed locally but never landed on GitHub: the
pipeline's saved summary + comments failed to post (validation error /
anchor mismatch), so this workflow re-publishes them with a deepagent
in the loop.

Submodules:

- :mod:`.types`     — the contract: :class:`RepairAndPublishWorkflowCtx`
  (resolved LLM + sandbox environment) and
  :class:`RepairAndPublishWorkflowInput` (the review run id), the
  loaded :class:`UnpublishedReview`, the :class:`PublishedReview`
  outcome, and the workflow's :class:`RepairAndPublishResult`. Ids are
  branded types from :mod:`app.utils.branded`.
- :mod:`.errors`    — error values (BaseModel, ``retryable`` flag +
  branded identity) returned by the pure step functions, plus the
  raised step-exception wrappers used by the DBOS step edges.
- :mod:`.helpers`   — pure helpers: the repair-agent story / user
  prompts and the draft → GitHub-item conversion.
- :mod:`.workflow`  — the :func:`repairAndPublishReviewWorkflow` DBOS
  orchestrator and its deterministic id helper.
- :mod:`.steps`     — one file per I/O boundary: check, delete-repo
  cleanup, repair-and-publish (deepagent harness), save back-links. The
  sandbox create / clone / diff / split / kill steps are imported from
  :mod:`app.workflows.review.steps` for exact parity with the review
  pipeline.
"""

from __future__ import annotations

from app.workflows.repair_and_publish.errors import (
    CheckError,
    DeleteRepoError,
    PublishError,
    RepairPublishError,
    RepairPublishStepFailure,
    SaveError,
    TransientRepairPublishStepFailure,
    shouldRetry,
)
from app.workflows.repair_and_publish.types import (
    CommentRow,
    PublishedReview,
    RepairAndPublishReason,
    RepairAndPublishResult,
    RepairAndPublishWorkflowCtx,
    RepairAndPublishWorkflowInput,
    UnpublishedReview,
)
from app.workflows.repair_and_publish.workflow import (
    repairAndPublishReviewWorkflow,
)

__all__ = [
    "CheckError",
    "CommentRow",
    "DeleteRepoError",
    "PublishedReview",
    "PublishError",
    "RepairAndPublishReason",
    "RepairAndPublishResult",
    "RepairAndPublishWorkflowCtx",
    "RepairAndPublishWorkflowInput",
    "RepairPublishError",
    "RepairPublishStepFailure",
    "SaveError",
    "TransientRepairPublishStepFailure",
    "UnpublishedReview",
    "repairAndPublishReviewWorkflow",
    "shouldRetry",
]
