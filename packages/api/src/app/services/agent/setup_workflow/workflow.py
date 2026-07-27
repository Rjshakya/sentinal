"""DBOS durable workflow for the per-repo setup pipeline.

The workflow is a straight-line sequence of typed
:func:`@DBOS.step` calls. Each step raises a :class:`SetupError`
subclass on failure; DBOS retries when the raised exception is a
:class:`TransientSetupError` and short-circuits when it is a plain
:class:`SetupError`. The workflow body converts any
:class:`SetupError` it catches into a flattened
:class:`app.services.agent.models.SetupResult` and persists it so the
dashboard always has a row to show.

Idempotency: the workflow id is
``f"setup:{user_id}:{github_repo_id}"``. A second ``POST /ai/repo/setup``
for the same repo reuses the existing workflow if it is still
running, and returns the cached result if it has already completed.
The router decides what to do for a workflow in ``ERROR`` state — it
starts a fresh one (see :mod:`app.routers.ai`).

Sandbox lifecycle: created in the first step, paused in the
``finally`` block. The :class:`RepoContext` carries the durable
``sandbox_id`` between steps; each step reconnects via
:meth:`E2BSandbox.connect`.
"""

from __future__ import annotations

import logging
from typing import Optional

from dbos import DBOS

from app.services.agent.setup_workflow.errors import SetupError
from app.services.agent.setup_workflow.steps import (
    ensure_repo_and_sandbox_step,
    git_clone_step,
    mint_installation_token_step,
    stop_setup_sandbox_step,
)
from app.services.agent.setup_workflow.types import (
    RepoContext,
    SetupWorkflowInput,
    SetupWorkflowResult,
)

log = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Workflow                                                                     #
# --------------------------------------------------------------------------- #


@DBOS.workflow()
async def setup_workflow(input: SetupWorkflowInput) -> SetupWorkflowResult:
    """Durable workflow: configure one repo end-to-end.

    Sequence: ensure repo + sandbox → mint token → git clone → run
    agent → persist result. ``stop_sandbox_step`` runs in
    ``finally`` so the sandbox is paused (not killed) regardless of
    the outcome. The ``try / except SetupError`` block flattens any
    typed step error into a :class:`SetupResult(ok=False)` so the
    persisted row is always present.
    """
    ctx: Optional[RepoContext] = None
    try:
        ctx = await ensure_repo_and_sandbox_step(input)

        token = await mint_installation_token_step(
            github_installation_id=ctx.github_installation_id,
        )

        await git_clone_step(
            ctx=ctx,
            install_token=token,
        )

        return SetupWorkflowResult(github_repo_id=ctx.github_installation_id)
    except SetupError as exc:
        log.warning(
            "setup_workflow: caught %s for user_id=%s repo_id=%s: %s",
            type(exc).__name__,
            input.user_id,
            input.github_repo_id,
            exc,
        )

        raise
    finally:
        if ctx is not None:
            await stop_setup_sandbox_step(
                sandbox_id=ctx.sandbox_id,
                sandbox_name=ctx.sandbox_name,
                repo_id=ctx.repo_id,
                user_id=ctx.user_id,
            )


__all__ = [
    "RepoContext",
    "SetupWorkflowInput",
    "SetupWorkflowResult",
    "setup_workflow",
]
