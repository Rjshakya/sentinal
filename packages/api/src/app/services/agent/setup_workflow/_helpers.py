"""Pure helpers for the setup pipeline.

No I/O, no session, no clock, no settings reads. Every function in
this module is testable with ``assert f(x) == y``.

The previous implementation lived inside
``app.services.agent.setup_pipeline``; this module is the clean-room
replacement that the new DBOS workflow imports.
"""

from __future__ import annotations

from app.core.sandbox.types import CommandResult
from app.services.agent.models import SetupResult
from app.services.agent.setup_workflow.errors import (
    GitCloneError,
    GitCloneTransientError,
    InstallTokenMintError,
    InstallationNotFoundError,
    SetupAgentCrashedError,
    SetupAgentNoStructuredResponseError,
    SetupAgentRateLimitedError,
    SetupError,
    TransientSetupError,
)


__all__ = [
    "build_authenticated_clone_url",
    "check_git_clone_result",
    "flatten_setup_error_to_setup_result",
    "truncate_command_output",
]


def build_authenticated_clone_url(
    *, install_token: str, owner: str, name: str
) -> str:
    """Build the authenticated HTTPS clone URL.

    GitHub's recommended way to authenticate ``git`` operations from
    CI: embed the install token as the basic-auth user
    (``x-access-token:<token>``). Works for both public and private
    repos. The token grants exactly the scopes the GitHub App was
    installed with, so this is the right primitive for cloning on the
    user's behalf.
    """
    return f"https://x-access-token:{install_token}@github.com/{owner}/{name}.git"


def truncate_command_output(result: CommandResult, *, max_chars: int = 500) -> str:
    """Take a :class:`CommandResult` and return a short string tail.

    Prefers ``stderr`` (which usually has the failure cause), falls
    back to ``stdout``, strips whitespace, and truncates to
    ``max_chars``. The output is meant to be embedded in
    :class:`GitCloneError`'s ``output_tail`` and ultimately in the
    dashboard's :class:`SetupResult.notes` — keep it short.
    """
    raw = (result.stderr or result.stdout or "").strip()
    return raw[:max_chars]


def check_git_clone_result(result: CommandResult) -> None:
    """Raise the appropriate typed error for a non-success clone result.

    The :meth:`BaseSandbox.execute` contract reports a sandbox-level
    failure as ``exit_code == -1`` with the cause in
    :attr:`CommandResult.error`; a real ``git`` failure is
    ``exit_code > 0`` with the cause in :attr:`CommandResult.stderr`.
    This helper maps both into the typed error hierarchy so the
    calling step can let one ``except`` block handle them::

        try:
            clone = await sandbox.execute("git clone …")
            check_git_clone_result(clone)
        except GitCloneTransientError:
            # DBOS retries (TransientSetupError)
            raise
        except GitCloneError:
            # Final, do not retry
            raise

    - ``exit_code == 0``  → return (no error).
    - ``exit_code == -1`` → raise :class:`GitCloneTransientError`
      (sandbox disconnect / command runner failure).
    - ``exit_code > 0``   → raise :class:`GitCloneError` (real
      git failure: bad token, missing repo, network, etc.).
    """
    if result.exit_code == 0:
        return
    tail = truncate_command_output(result)
    if result.exit_code == -1:
        raise GitCloneTransientError(cause=tail or "sandbox command runner failure")
    raise GitCloneError(exit_code=result.exit_code, output_tail=tail)


def flatten_setup_error_to_setup_result(error: SetupError) -> SetupResult:
    """Convert any :class:`SetupError` variant to an ``ok=False``
    :class:`SetupResult`.

    Pure — single :func:`match` over the closed union. The router's
    status endpoint and the workflow's :keyword:`except SetupError`
    block both call this so the dashboard always sees the same shape.
    """
    match error:
        case InstallationNotFoundError(installation_id=installation_id, user_id=user_id):
            notes = (
                f"installation_id={installation_id!r} does not "
                f"belong to user_id={user_id!r}"
            )
        case InstallTokenMintError(cause=cause):
            notes = f"install_token_mint failed: {cause}"
        case GitCloneError(exit_code=exit_code, output_tail=output_tail):
            notes = f"git clone failed (exit_code={exit_code}): {output_tail}"
        case GitCloneTransientError(cause=cause):
            notes = f"git clone transient sandbox failure: {cause}"
        case SetupAgentCrashedError(cause=cause):
            notes = f"setup agent crashed: {cause}"
        case SetupAgentRateLimitedError(cause=cause):
            notes = f"setup agent rate-limited: {cause}"
        case SetupAgentNoStructuredResponseError(message_kinds=message_kinds):
            notes = (
                "setup agent returned no structured_response "
                f"(messages={list(message_kinds)})"
            )
        case TransientSetupError():
            notes = f"setup pipeline failed: {error}"
        case _:
            notes = f"setup pipeline failed: {error}"
    return SetupResult(
        ok=False,
        ecosystem="none",
        manager=None,
        install_cmd=None,
        duration_s=0.0,
        notes=notes,
        bootstrapped_tools=[],
    )

