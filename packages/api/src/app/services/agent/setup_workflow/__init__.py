"""Setup pipeline as a DBOS durable workflow.

This subpackage is the new home of the "configure repo" flow. It
replaces the old ``app.services.agent.setup_pipeline`` /
``app.services.agent.setup_errors`` modules — those are left in place
but are no longer imported by the router. Every public symbol lives
under one of:

- :mod:`app.services.agent.setup_workflow.errors` — typed exception hierarchy.
- :mod:`app.services.agent.setup_workflow._helpers` — pure functions.
- :mod:`app.services.agent.setup_workflow.workflow` — the DBOS workflow.
- :mod:`app.services.agent.setup_workflow.steps` — the workflow's I/O steps.

Re-exports the workflow's public types so callers do not need to know
the internal layout.
"""

from __future__ import annotations

from app.services.agent.setup_workflow.errors import (
    GitCloneError,
    GitCloneTransientError,
    InstallTokenMintError,
    InstallationNotFoundError,
    SandboxCreateError,
    SetupAgentCrashedError,
    SetupAgentNoStructuredResponseError,
    SetupAgentRateLimitedError,
    SetupError,
    TransientSetupError,
)
from app.services.agent.setup_workflow.types import (
    RepoContext,
    SetupWorkflowInput,
    SetupWorkflowResult,
)
from app.services.agent.setup_workflow.workflow import setup_workflow


__all__ = [
    "GitCloneError",
    "GitCloneTransientError",
    "InstallTokenMintError",
    "InstallationNotFoundError",
    "RepoContext",
    "SandboxCreateError",
    "SetupAgentCrashedError",
    "SetupAgentNoStructuredResponseError",
    "SetupAgentRateLimitedError",
    "SetupError",
    "SetupWorkflowInput",
    "SetupWorkflowResult",
    "TransientSetupError",
    "setup_workflow",
]

