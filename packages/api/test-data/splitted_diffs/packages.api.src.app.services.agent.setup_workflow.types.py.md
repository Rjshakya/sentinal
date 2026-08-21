### packages/api/src/app/services/agent/setup_workflow/types.py

```diff

new file mode 100644
index 0000000..f4cf7b6
--- /dev/null
+++ b/packages/api/src/app/services/agent/setup_workflow/types.py
@@ -0,0 +1,87 @@
          2 +"""Shared Pydantic types for the setup pipeline.
          3 +
          4 +Extracted to break a circular import between
          5 +:mod:`app.services.agent.setup_workflow.workflow` (which orchestrates the
          6 +steps) and :mod:`app.services.agent.setup_workflow.steps` (which implement
          7 +them). The types here are the only safe inter-module dependency —
          8 +both the workflow and the step modules import from this file, not
          9 +from each other.
         10 +"""
         11 +
         12 +from __future__ import annotations
         13 +
         14 +from typing import Optional
         15 +
         16 +from pydantic import BaseModel, ConfigDict
         17 +
         18 +from app.core.llm import LLMConfig
         19 +
         20 +__all__ = [
         21 +    "RepoContext",
         22 +    "SetupWorkflowInput",
         23 +    "SetupWorkflowResult",
         24 +]
         25 +
         26 +
         27 +class SetupWorkflowInput(BaseModel):
         28 +    """Everything the workflow needs to configure one repo.
         29 +
         30 +    Frozen so DBOS can serialize it into its system database without
         31 +    accidental mutation. Holds the local :class:`Installation` id (a
         32 +    UUID), the GitHub-side identifiers (numeric repo id, owner,
         33 +    name), and the LLM configuration the agent will run with.
         34 +    """
         35 +
         36 +    model_config = ConfigDict(frozen=True)
         37 +
         38 +    user_id: str
         39 +    github_repo_id: int
         40 +    repo_owner: str
         41 +    repo_name: str
         42 +    installation_id: str  # local Installation.id (UUID)
         43 +    llm_config: LLMConfig
         44 +    default_branch: Optional[str] = None
         45 +
         46 +
         47 +class RepoContext(BaseModel):
         48 +    """Durable handle to the sandbox + repo, passed between steps.
         49 +
         50 +    Returned by :func:`ensure_repo_and_sandbox_step` and consumed by
         51 +    every subsequent step. ``sandbox_id`` and ``sandbox_name`` are
         52 +    stable across workflow resumes; the in-process
         53 +    :class:`AsyncSandbox` handle is rebuilt on demand via
         54 +    :meth:`E2BSandbox.connect`.
         55 +
         56 +    ``github_installation_id`` is the integer id the GitHub App mints
         57 +    tokens against; ``installation_id`` is the local :class:`app.models.installation.Installation`
         58 +    row's primary key — the router passes the latter, the workflow
         59 +    resolves the former in the first step.
         60 +    """
         61 +
         62 +    model_config = ConfigDict(frozen=True)
         63 +
         64 +    user_id: str
         65 +    repo_id: str  # local Repo.id (UUID)
         66 +    repo_owner: str
         67 +    repo_name: str
         68 +    sandbox_id: str
         69 +    sandbox_name: str
         70 +    installation_id: str  # local Installation.id (UUID)
         71 +    github_installation_id: int  # for token mint
         72 +
         73 +
         74 +class SetupWorkflowResult(BaseModel):
         75 +    """The workflow's return value.
         76 +
         77 +    ``error_name`` / ``error_message`` mirror the typed
         78 +    :class:`SetupError` that aborted the workflow, when any. Both
         79 +    are ``None`` on success.
         80 +
         81 +    Frozen so DBOS can serialize it.
         82 +    """
         83 +
         84 +    model_config = ConfigDict(frozen=True)
         85 +
         86 +    github_repo_id: int
         87 +    error_name: Optional[str] = None
         88 +    error_message: Optional[str] = None

```
