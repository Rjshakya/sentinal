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
- :mod:`.resolve_sandbox`     — find + connect the E2B sandbox.
- :mod:`.fetch_diff`          — write the unified diff into the sandbox.
- :mod:`.parse_diff`          — parse the diff, write ``diff.json``.
- :mod:`.upsert_pr`           — insert / update the :class:`PullRequest` row.
- :mod:`.invoke_agent`        — run the four review agents as four
  parallel durable steps; combine their outcomes.
- :mod:`.persist_summary`     — insert the :class:`ReviewSummary` row.
- :mod:`.persist_comments`    — insert the :class:`CodeComment` rows.
- :mod:`.persist_usage`       — insert the :class:`ReviewUsage` row.
- :mod:`.stop_sandbox`        — best-effort sandbox stop.
"""

from __future__ import annotations

from app.services.review.steps.fetch_diff import fetch_diff_step
from app.services.review.steps.invoke_agent import (
    combine_agent_outcomes,
    invoke_correctness_agent,
    invoke_correctness_agent_step,
    invoke_security_agent,
    invoke_security_agent_step,
    invoke_style_agent,
    invoke_style_agent_step,
    invoke_summary_agent,
    invoke_summary_agent_step,
)
from app.services.review.steps.parse_diff import parse_diff_step
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
from app.services.review.steps.stop_sandbox import stop_sandbox_step
from app.services.review.steps.upsert_pr import (
    upsert_pull_request,
    upsert_pull_request_tx,
)

__all__ = [
    "combine_agent_outcomes",
    "fetch_diff_step",
    "invoke_correctness_agent",
    "invoke_correctness_agent_step",
    "invoke_security_agent",
    "invoke_security_agent_step",
    "invoke_style_agent",
    "invoke_style_agent_step",
    "invoke_summary_agent",
    "invoke_summary_agent_step",
    "parse_diff_step",
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
    "stop_sandbox_step",
    "sum_total_usages",
    "upsert_pull_request",
    "upsert_pull_request_tx",
]
