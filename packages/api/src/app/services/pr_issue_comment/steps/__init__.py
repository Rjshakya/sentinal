"""DBOS-bound steps for the ``issue_comment`` trigger pipeline.

One module per I/O boundary used by
:func:`app.services.pr_issue_comment.workflow.trigger_issue_comment_workflow`.
Each step is a thin :func:`@DBOS.step` (or
:func:`@dbos_datasource.transaction` for DB-only work) that wraps a
single concern. Cross-step state is passed as Pydantic models so DBOS
can serialise the workflow state into its system database.

Modules:

- :mod:`.resolve_installation` — find the local :class:`Installation`
  row, return an :class:`app.services.pr_issue_comment.types.InstallationSnapshot`.
- :mod:`.resolve_repo_id`     — find the local :class:`Repo` id by
  GitHub-side ``github_repo_id``.
- :mod:`.fetch_pr_state`      — ``GET /repos/{owner}/{repo}/pulls/{pr}``
  to read the current ``head_sha`` and other PR fields not on the
  comment payload.
- :mod:`.add_reaction`        — fire-and-forget 👀 reaction on the
  triggering comment.
- :mod:`.resolve_llm_config`  — load the per-user :class:`app.core.llm.LLMConfig`
  (or fall back to the env-driven default).
- :mod:`.build_review_input`  — pure: assemble the inner
  :class:`app.services.review.workflow_types.ReviewWorkflowInput`.
- :mod:`.dispatch_review`     — start the inner ``review_workflow``
  via :func:`DBOS.start_workflow_async` with the deterministic
  ``review:{local_repo_id}:{pr_number}:{head_sha[:7]}`` workflow id.
  Plain async helper, **not** a :func:`@DBOS.step`: DBOS forbids
  starting a child workflow from inside a step, so it runs directly
  in the trigger workflow's body.
"""

from __future__ import annotations

from app.services.pr_issue_comment.steps.add_reaction import add_eyes_reaction_step
from app.services.pr_issue_comment.steps.build_review_input import (
    build_review_input_step,
)
from app.services.pr_issue_comment.steps.dispatch_review import run_review_workflow
from app.services.pr_issue_comment.steps.fetch_pr_state import fetch_pr_state_step
from app.services.pr_issue_comment.steps.resolve_installation import (
    resolve_installation_step,
)
from app.services.pr_issue_comment.steps.resolve_llm_config import (
    resolve_llm_config_step,
)
from app.services.pr_issue_comment.steps.resolve_repo_id import resolve_repo_id_step

__all__ = [
    "add_eyes_reaction_step",
    "build_review_input_step",
    "fetch_pr_state_step",
    "resolve_installation_step",
    "resolve_llm_config_step",
    "resolve_repo_id_step",
    "run_review_workflow",
]
