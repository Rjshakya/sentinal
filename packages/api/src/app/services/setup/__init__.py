"""Setup pipeline: durable DBOS workflow for the per-repo
'configure repo' flow.

End-to-end the workflow:

1. Upserts the local :class:`app.models.repo.Repo` row.
2. Creates an E2B sandbox and persists the :class:`app.models.sandbox.Sandbox`
   row keyed on the E2B-assigned ``sandbox_id``.
3. Mints a fresh GitHub installation access token.
4. Shallow-clones the repo into the sandbox.
5. Optionally dispatches the indexing workflow as a fire-and-forget
   follow-up (controlled by ``Settings.indexing_configured``).
6. Pauses the sandbox in ``finally``.

Public surface:

- :func:`setup_workflow` -- the DBOS durable workflow.
- :class:`SetupWorkflowInput` / :class:`SetupWorkflowResult` / :class:`RepoContext`
  -- the Pydantic models crossing the workflow boundary.
- :mod:`app.services.setup.errors` -- the typed exception hierarchy
  (``SetupError`` / ``TransientSetupError``).
"""

from __future__ import annotations

from app.services.setup.errors import (
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
from app.services.setup.types import (
    RepoContext,
    SetupWorkflowInput,
    SetupWorkflowResult,
)
from app.services.setup.workflow import setup_workflow

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
