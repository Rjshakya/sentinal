"""Review pipeline steps.

Each module in this package owns a single I/O boundary used by the
orchestrator in :mod:`app.services.review.workflow`. The
DBOS-wrapped variants (``*_tx`` / ``*_step``) carry the
``@dbos_datasource.transaction()`` / ``@DBOS.step()`` decorator and
are what the workflow actually calls. The pure helpers (without
suffix) are also re-exported here so tests and any future non-DBOS
caller can reuse them.

Modules:

- :mod:`.resolve_repo`        — find the local :class:`Repo` row.
- :mod:`.create_sandbox`      — create the per-run ephemeral E2B sandbox.
- :mod:`.clone_repo`          — clone the repo into the sandbox at review time.
- :mod:`.fetch_diff`          — write the unified diff into the sandbox.
- :mod:`.split_diff`          — split ``file.diff`` into per-file chunks.
- :mod:`.upsert_pr`           — insert / update the :class:`PullRequest` row.
- :mod:`.invoke_agent`        — run the two review agents as two
  parallel durable steps; combine their outcomes.
- :mod:`.extract_result`      — turn the agents' free-form output
  into structured payloads via a small OpenAI model (DBOS steps).
- :mod:`.persist_summary`     — insert the :class:`ReviewSummary` row.
- :mod:`.persist_comments`    — insert the :class:`CodeComment` rows.
- :mod:`.persist_usage`       — insert the :class:`ReviewUsage` row.
- :mod:`.review_run_steps`    — the ``review`` lifecycle mirror
  (running / stopped / errored transitions + ``build_error_context``).
- :mod:`.stop_sandbox`        — best-effort sandbox pause (legacy)
  and destroy (:func:`.kill_sandbox_step`, used by the workflow's ``finally``).
"""

from __future__ import annotations

from app.services.review.steps.clone_repo import clone_repo_step
from app.services.review.steps.create_sandbox import create_review_sandbox_step
from app.services.review.steps.fetch_diff import fetch_diff_step
from app.services.review.steps.extract_result import (
    build_extractor_config,
    extract_comments_result_step,
    extract_summary_result_step,
)
from app.services.review.steps.invoke_agent import (
    combine_agent_outcomes,
    invoke_comments_agent,
    invoke_comments_agent_step,
    invoke_summary_agent,
    invoke_summary_agent_step,
    run_extractor_lanes,
)
from app.services.review.steps.persist_comments import (
    persist_code_comments,
    persist_code_comments_tx,
)
from app.services.review.steps.persist_summary import (
    persist_review_summary,
    persist_review_summary_tx,
)
from app.services.review.steps.persist_usage import (
    persist_review_usage,
    persist_review_usage_tx,
    sum_total_usages,
)
from app.services.review.steps.resolve_repo import resolve_repo, resolve_repo_tx
from app.services.review.steps.resolve_sandbox import (
    resolve_sandbox,
    resolve_sandbox_step,
)
from app.services.review.steps.review_run_steps import (
    build_error_context,
    mark_review_is_errored_step,
    mark_review_is_running_step,
    mark_review_is_stopped_step,
)
from app.services.review.steps.split_diff import split_diff_step
from app.services.review.steps.stop_sandbox import kill_sandbox_step, stop_sandbox_step
from app.services.review.steps.update_repo import update_repo, update_repo_step
from app.services.review.steps.upsert_pr import (
    upsert_pull_request,
    upsert_pull_request_tx,
)

__all__ = [
    "build_error_context",
    "build_extractor_config",
    "clone_repo_step",
    "combine_agent_outcomes",
    "create_review_sandbox_step",
    "extract_comments_result_step",
    "extract_summary_result_step",
    "fetch_diff_step",
    "invoke_comments_agent",
    "invoke_comments_agent_step",
    "invoke_summary_agent",
    "invoke_summary_agent_step",
    "kill_sandbox_step",
    "mark_review_is_errored_step",
    "mark_review_is_running_step",
    "mark_review_is_stopped_step",
    "persist_code_comments",
    "persist_code_comments_tx",
    "persist_review_summary",
    "persist_review_summary_tx",
    "persist_review_usage",
    "persist_review_usage_tx",
    "resolve_repo",
    "resolve_repo_tx",
    "resolve_sandbox",
    "resolve_sandbox_step",
    "run_extractor_lanes",
    "split_diff_step",
    "stop_sandbox_step",
    "sum_total_usages",
    "update_repo",
    "update_repo_step",
    "upsert_pull_request",
    "upsert_pull_request_tx",
]
