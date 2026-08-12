"""Step 2: shallow-clone the repo into the sandbox.

Shallow clone (``--depth 1``), pinned to ``default_branch`` when
known, into :func:`app.utils.util.workspace_path`. The
:func:`check_git_clone` helper maps the :class:`CommandResult` to the
typed error hierarchy: exit 0 → ok; exit -1 → transient (sandbox
runner failure); exit > 0 → final (bad URL, missing repo, auth
failure).

DBOS keys step registration on ``__name__``. Named ``gitCloneToSandbox``
to avoid colliding with the setup pipeline's own ``git_clone_step``
in :mod:`app.services.agent.setup_workflow`.
"""

from __future__ import annotations

import logging
import shlex

from dbos import DBOS

from app.core.sandbox.e2b import E2BSandbox
from app.core.sandbox.types import CommandResult
from app.services.indexing.errors import (
    IndexGitCloneError,
    IndexGitCloneTransientError,
    _should_retry_index,
)
from app.services.indexing.helpers import command_output_tail
from app.services.indexing.steps._internal import connect_index_sandbox
from app.services.indexing.types import IndexContext
from app.utils.util import workspace_path

log = logging.getLogger(__name__)

CLONE_TIMEOUT_S: float = 300.0
"""Upper bound on the wall-clock duration of a single ``git clone``."""


def build_clone_command(ctx: IndexContext) -> str:
    """Build the shell command for the sandbox (pure, testable)."""
    parts = ["git", "clone", "--depth", "1"]
    if ctx.default_branch:
        parts += ["--single-branch", "--branch", ctx.default_branch]
    parts += [ctx.repo_url, ctx.repo_name]
    return " ".join(shlex.quote(part) for part in parts)


def check_git_clone(result: CommandResult) -> None:
    """Map a clone :class:`CommandResult` to the typed error hierarchy."""
    if result.exit_code == 0:
        return
    tail = command_output_tail(result)
    if result.exit_code == -1:
        raise IndexGitCloneTransientError(
            cause=tail or "sandbox command runner failure"
        )
    raise IndexGitCloneError(exit_code=result.exit_code, output_tail=tail)


@DBOS.step(
    retries_allowed=True,
    max_attempts=3,
    should_retry=_should_retry_index,
)
async def gitCloneToSandbox(*, ctx: IndexContext) -> None:
    """Shallow-clone ``ctx.repo_url`` into the sandbox workspace.

    Reconnects to the sandbox by id. Reconnect failures and runner
    dropouts raise transient errors (DBOS retries); a real ``git``
    failure (bad URL, auth, missing repo) is final.
    """
    try:
        sandbox: E2BSandbox = await connect_index_sandbox(ctx)
        # The E2B SDK raises InvalidArgumentException when the execute
        # cwd does not exist; fresh sandboxes have no workspace dir.
        # Mirror the setup pipeline, which creates it before cloning.
        await sandbox.fs_create_folder(workspace_path())
        result = await sandbox.execute(
            build_clone_command(ctx),
            cwd=workspace_path(),
            timeout=CLONE_TIMEOUT_S,
        )
        check_git_clone(result)
    except (IndexGitCloneError, IndexGitCloneTransientError):
        raise
    except Exception as exc:
        log.warning(
            "index_git_clone: unexpected failure owner=%s repo=%s cause=%s: %s",
            ctx.repo_owner,
            ctx.repo_name,
            type(exc).__name__,
            exc,
        )
        raise IndexGitCloneTransientError(
            cause=f"{type(exc).__name__}: {exc}"
        ) from exc

    log.info(
        "index_git_clone: ok owner=%s repo=%s sandbox_id=%s",
        ctx.repo_owner,
        ctx.repo_name,
        ctx.sandbox_id,
    )


__all__ = ["build_clone_command", "check_git_clone", "gitCloneToSandbox"]
