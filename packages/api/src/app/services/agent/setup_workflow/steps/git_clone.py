"""Step 3: shallow ``git clone`` of the repo into the E2B sandbox.

Reconnects to the sandbox by id (the in-process handle is gone
after a workflow resume), creates the workspace folder, runs the
clone with the authenticated URL, and validates the exit code.
"""

from __future__ import annotations

import logging
from typing import cast

from dbos import DBOS

from app.core.sandbox.e2b import E2BSandbox, E2BSandboxSpec
from app.core.sandbox.factory import build_default_spec
from app.services.agent.setup_workflow._helpers import (
    build_authenticated_clone_url,
    check_git_clone_result,
)
from app.services.agent.setup_workflow.types import RepoContext
from app.utils.util import workspace_path

log = logging.getLogger(__name__)

CLONE_TIMEOUT_S: float = 300.0
"""Upper bound on the wall-clock duration of a single ``git clone``.

300 s covers most first-time clones of moderate-size public repos.
Private monorepos that have to negotiate through a slow network
will hit this; the workflow's step retry policy handles it as a
:class:`GitCloneTransientError` (sandbox-side runner failure) or a
:class:`GitCloneError` (real ``git`` failure) depending on the exit
code path.
"""


def _should_retry_setup(exc: BaseException) -> bool:
    from app.services.agent.setup_workflow.errors import TransientSetupError

    return isinstance(exc, TransientSetupError)


@DBOS.step(
    retries_allowed=True,
    max_attempts=2,
    should_retry=_should_retry_setup,
)
async def git_clone_step(
    *,
    ctx: RepoContext,
    install_token: str,
) -> None:
    """Shallow-clone ``ctx.repo_owner/ctx.repo_name`` into the sandbox.

    Reconnects to the E2B sandbox via
    :meth:`E2BSandbox.connect`. The reconnect itself is wrapped —
    transient connect failures raise
    :class:`GitCloneTransientError` (retry) while other SDK errors
    are re-raised as :class:`GitCloneError` (final).

    The :func:`check_git_clone_result` helper maps the
    ``CommandResult`` to the typed error hierarchy:

    - ``exit_code == 0``  → success
    - ``exit_code == -1`` → :class:`GitCloneTransientError`
      (sandbox-side runner failure — DBOS retries)
    - ``exit_code > 0``   → :class:`GitCloneError` (real git failure)

    Raises:
        GitCloneTransientError: sandbox-side command runner failure.
            Retried by DBOS. The clone step reconnects via
            :meth:`E2BSandbox.connect` and re-runs the command, so a
            transient disconnect does not require a fresh sandbox.
        GitCloneError: the ``git clone`` itself failed (non-zero
            exit code, bad token, missing repo, transport error).
            Final — not retried.
    """
    spec: E2BSandboxSpec = cast(E2BSandboxSpec, build_default_spec("e2b"))

    try:
        sandbox = await E2BSandbox.connect(
            sandbox_id=ctx.sandbox_id,
            sandbox_name=ctx.sandbox_name,
            repo_id=ctx.repo_id,
            user_id=ctx.user_id,
            spec=spec,
            timeout=60 * 60,
            api_key=spec.api_key,
        )
    except Exception as exc:
        log.warning(
            "git_clone: sandbox reconnect failed (will retry): user_id=%s "
            "repo_id=%s sandbox_id=%s cause=%s: %s",
            ctx.user_id,
            ctx.repo_id,
            ctx.sandbox_id,
            type(exc).__name__,
            exc,
        )
        # Treat all reconnect failures as transient — DBOS retries.
        from app.services.agent.setup_workflow.errors import GitCloneTransientError

        raise GitCloneTransientError(
            cause=f"reconnect failed: {type(exc).__name__}: {exc}"
        ) from exc

    try:
        await sandbox.fs_create_folder(workspace_path())
        clone_url = build_authenticated_clone_url(
            install_token=install_token,
            owner=ctx.repo_owner,
            name=ctx.repo_name,
        )
        result = await sandbox.execute(
            f"git clone {clone_url} {ctx.repo_name}",
            cwd=workspace_path(),
            timeout=CLONE_TIMEOUT_S,
        )
        check_git_clone_result(result)
    finally:
        try:
            await sandbox.stop()
        except Exception:
            log.exception(
                "git_clone: failed to stop sandbox after clone: sandbox_id=%s",
                ctx.sandbox_id,
            )

    log.info(
        "git_clone: ok user_id=%s repo_id=%s sandbox_id=%s",
        ctx.user_id,
        ctx.repo_id,
        ctx.sandbox_id,
    )


__all__ = ["git_clone_step"]

