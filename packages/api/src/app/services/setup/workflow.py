"""DBOS durable workflow for the per-repo setup pipeline.

The workflow is a straight-line sequence of typed
:func:`@DBOS.step` calls. Each step raises a :class:`SetupError`
subclass on failure; DBOS retries when the raised exception is a
:class:`TransientSetupError` and short-circuits when it is a plain
:class:`SetupError`. The workflow re-raises any caught
:class:`SetupError` so DBOS records the typed error name + message on
the workflow result, which the router surfaces through
:class:`SetupWorkflowResult`.

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

from dbos import DBOS, SetWorkflowID

from app.services.setup.errors import SetupError
from app.services.setup.steps import (
    ensure_repo_and_sandbox_step,
    git_clone_step,
    mint_installation_token_step,
    stop_setup_sandbox_step,
)
from app.services.setup.types import (
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

    Sequence: ensure repo + sandbox → mint token → git clone →
    (optionally) dispatch :func:`app.services.indexing.workflow.indexRepo`.

    ``stop_setup_sandbox_step`` runs in ``finally`` so the sandbox
    is paused (not killed) regardless of the outcome. Any typed
    :class:`SetupError` re-raises so DBOS records the error on the
    workflow result; the router surfaces it through
    :class:`SetupWorkflowResult`.

    The auto-dispatch at the end is fire-and-forget: setup returns
    SUCCESS regardless of indexing's outcome. An indexing failure
    only flips the per-repo ``is_indexed`` flag to ``false`` via the
    mirror steps in :mod:`app.services.indexing.steps.update_repo`;
    the user can always click "Index" manually to retry.
    """
    ctx: RepoContext | None = None
    try:
        ctx = await ensure_repo_and_sandbox_step(input)

        token = await mint_installation_token_step(
            github_installation_id=ctx.github_installation_id,
        )

        await git_clone_step(
            ctx=ctx,
            install_token=token,
        )

        if input.index_after_setup:
            await _dispatch_indexing(
                user_id=input.user_id,
                repo_owner=ctx.repo_owner,
                repo_name=ctx.repo_name,
                default_branch=input.default_branch,
                local_repo_id=ctx.repo_id,
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


async def _dispatch_indexing(
    *,
    user_id: str,
    repo_owner: str,
    repo_name: str,
    default_branch: str | None,
    local_repo_id: str,
) -> None:
    """Fire-and-forget dispatch of :func:`indexRepo` for this repo.

    Imports are inside the function to avoid a circular import with
    :mod:`app.services.indexing.workflow` (which does not import
    setup). Failures are logged and swallowed — the setup workflow
    must not fail because indexing failed.

    ``local_repo_id`` is the parent :class:`app.models.repo.Repo.id`
    (UUID) so the indexing workflow can flip ``is_indexed`` on
    terminal ``SUCCESS`` / ``ERROR``.
    """
    try:
        from app.core.config import settings
        from app.services.indexing.helpers import index_workflow_id
        from app.services.indexing.types import IndexWorkflowInput
        from app.services.indexing.workflow import indexRepo

        if not settings.indexing_configured:
            log.info(
                "setup_workflow: skipping auto-index (indexing not configured) "
                "owner=%s repo=%s",
                repo_owner,
                repo_name,
            )
            return

        clone_url = f"https://github.com/{repo_owner}/{repo_name}.git"
        workflow_id = index_workflow_id(repo_owner, repo_name)
        with SetWorkflowID(workflow_id):
            await DBOS.start_workflow_async(
                indexRepo,
                IndexWorkflowInput(
                    user_id=user_id,
                    repo_owner=repo_owner,
                    repo_name=repo_name,
                    repo_url=clone_url,
                    default_branch=default_branch,
                    local_repo_id=local_repo_id,
                ),
            )
        log.info(
            "setup_workflow: dispatched indexer workflow_id=%s owner=%s repo=%s",
            workflow_id,
            repo_owner,
            repo_name,
        )
    except Exception:
        log.exception(
            "setup_workflow: auto-index dispatch failed owner=%s repo=%s",
            repo_owner,
            repo_name,
        )


__all__ = [
    "RepoContext",
    "SetupWorkflowInput",
    "SetupWorkflowResult",
    "setup_workflow",
]
