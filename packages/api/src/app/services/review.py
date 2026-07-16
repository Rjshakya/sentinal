"""Review service facade.

The review orchestrator now lives in
:mod:`app.services.agent.review_pipeline`. This module re-exports the
public surface so callers can continue importing from
``app.services.review``.
"""

from app.services.agent.review_pipeline import (
    DiffProvider,
    E2BReviewAgentRunner,
    GivenDiffProvider,
    ReviewAgentRunner,
    ReviewPipelineError,
    ReviewRunResult,
    SandboxDiffProvider,
    connect_active_sandbox,
    flatten_review_error_to_message,
    map_drafts_to_comment_rows,
    run_review_pipeline,
)

__all__ = [
    "DiffProvider",
    "E2BReviewAgentRunner",
    "GivenDiffProvider",
    "ReviewAgentRunner",
    "ReviewPipelineError",
    "ReviewRunResult",
    "SandboxDiffProvider",
    "connect_active_sandbox",
    "flatten_review_error_to_message",
    "map_drafts_to_comment_rows",
    "run_review_pipeline",
]
