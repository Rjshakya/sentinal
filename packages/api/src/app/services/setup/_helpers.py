"""Pure helpers for the setup pipeline.

No I/O, no session, no clock, no settings reads. Every function in
this module is testable with ``assert f(x) == y``.
"""

from __future__ import annotations

from app.core.sandbox.types import CommandResult
from app.services.setup.errors import (
    GitCloneError,
    GitCloneTransientError,
)

__all__ = [
    "build_authenticated_clone_url",
    "check_git_clone_result",
    "truncate_command_output",
]


def build_authenticated_clone_url(*, install_token: str, owner: str, name: str) -> str:
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
    :class:`GitCloneError`'s ``output_tail`` — keep it short.
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
