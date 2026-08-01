"""Shared Pydantic types for the setup pipeline.

Extracted to break a circular import between
:mod:`app.services.agent.setup_workflow.workflow` (which orchestrates the
steps) and :mod:`app.services.agent.setup_workflow.steps` (which implement
them). The types here are the only safe inter-module dependency —
both the workflow and the step modules import from this file, not
from each other.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict

from app.core.llm import LLMConfig

__all__ = [
    "RepoContext",
    "SetupWorkflowInput",
    "SetupWorkflowResult",
]


class SetupWorkflowInput(BaseModel):
    """Everything the workflow needs to configure one repo.

    Frozen so DBOS can serialize it into its system database without
    accidental mutation. Holds the local :class:`Installation` id (a
    UUID), the GitHub-side identifiers (numeric repo id, owner,
    name), and the LLM configuration the agent will run with.
    """

    model_config = ConfigDict(frozen=True)

    user_id: str
    github_repo_id: int
    repo_owner: str
    repo_name: str
    installation_id: str  # local Installation.id (UUID)
    llm_config: LLMConfig


class RepoContext(BaseModel):
    """Durable handle to the sandbox + repo, passed between steps.

    Returned by :func:`ensure_repo_and_sandbox_step` and consumed by
    every subsequent step. ``sandbox_id`` and ``sandbox_name`` are
    stable across workflow resumes; the in-process
    :class:`AsyncSandbox` handle is rebuilt on demand via
    :meth:`E2BSandbox.connect`.

    ``github_installation_id`` is the integer id the GitHub App mints
    tokens against; ``installation_id`` is the local :class:`app.models.installation.Installation`
    row's primary key — the router passes the latter, the workflow
    resolves the former in the first step.
    """

    model_config = ConfigDict(frozen=True)

    user_id: str
    repo_id: str  # local Repo.id (UUID)
    repo_owner: str
    repo_name: str
    sandbox_id: str
    sandbox_name: str
    installation_id: str  # local Installation.id (UUID)
    github_installation_id: int  # for token mint


class SetupWorkflowResult(BaseModel):
    """The workflow's return value.

    ``setup`` is the canonical :class:`SetupResult` (always present —
    ``ok=False`` on failure, with ``notes`` describing the cause).
    ``error_name`` / ``error_message`` mirror the typed error for
    the API status endpoint; they are ``None`` on success.

    Frozen so DBOS can serialize it.
    """

    model_config = ConfigDict(frozen=True)

    github_repo_id: int
    error_name: Optional[str] = None
    error_message: Optional[str] = None
