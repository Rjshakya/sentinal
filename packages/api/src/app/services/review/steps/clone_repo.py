"""DBOS durable step: clone the repo into the per-review sandbox.

Replaces the setup-time clone: the review pipeline is stateless, so
:func:`clone_repo_step` clones the repo at review time into the fresh
sandbox created by
:func:`app.services.review.steps.create_sandbox.create_review_sandbox_step`.

The clone runs from the **default branch** (plain ``git clone``, like
the setup pipeline). The PR head lives on another branch (or a fork
ref), so the step then best-effort fetches ``refs/pull/{pr}/head``;
:func:`app.services.review.steps.fetch_diff.fetch_diff_step`'s existing
``git fetch origin`` remains the catch-all that pulls the PR branch
before ``git diff`` runs.

Security posture (mirrors the indexing pipeline's clone): the
installation token is delivered to the sandbox **via the environment**
(``envs``), referenced as ``${GITHUB_TOKEN}`` in the URL and expanded by
the sandbox shell — the token never appears in a process argv. Every
interpolated command part is ``shlex.quote``d.

Exit-code contract (mirrors :mod:`app.services.setup._helpers`):
``0`` success, ``-1`` transient runner dropout (DBOS retries), ``>0``
final ``git`` failure (:class:`app.services.review.errors.RepoCloneError`).
"""

from __future__ import annotations

import logging
import shlex

from dbos import DBOS

from app.core.github_app import mint_installation_token
from app.core.sandbox.e2b import E2BSandbox
from app.core.sandbox.types import CommandResult
from app.services.review._internal import _SHOULD_RETRY_TRANSIENT, _e2b_spec
from app.services.review.diff import truncate_diff_output
from app.services.review.errors import RepoCloneError, RepoCloneTransientError
from app.utils.util import workspace_path

log = logging.getLogger(__name__)

CLONE_TIMEOUT_S: float = 300.0
"""Upper bound on the wall-clock duration of a single ``git clone``."""

PR_REF_FETCH_TIMEOUT_S: float = 120.0
"""Upper bound on the wall-clock duration of the PR-head ref fetch."""

_TOKEN_ENV_VAR: str = "GITHUB_TOKEN"
"""Sandbox env var carrying the installation token for the clone."""


def build_review_clone_command(*, repo_owner: str, repo_name: str) -> str:
    """Build the shell command that clones the repo's default branch.

    Pure and testable. The token is referenced as ``${GITHUB_TOKEN}``
    inside the HTTPS URL and resolved by the sandbox shell from the
    step's ``envs`` — never interpolated into the command string.
    ``repo_name`` (the clone destination) is shell-quoted; the URL
    interpolates ``repo_owner`` / ``repo_name`` verbatim (GitHub's
    owner/repo charset contains no whitespace or shell metacharacters).
    """
    url = (
        f"https://x-access-token:${{{_TOKEN_ENV_VAR}}}"
        f"@github.com/{repo_owner}/{repo_name}.git"
    )
    return f"git clone {url} {shlex.quote(repo_name)}"


def build_pr_ref_fetch_command(*, pr_number: int) -> str:
    """Build the shell command fetching the PR head ref (best-effort).

    ``refs/pull/{pr_number}/head`` is advertised by GitHub for every
    open PR — same-repo and fork PRs alike — so the fetched head commit
    is available for ``git diff`` even when the PR branch was never
    pushed to origin.
    """
    return (
        f"git fetch origin refs/pull/{pr_number}/head:"
        f"refs/remotes/origin/pr-{pr_number}"
    )


def check_clone_result(
    result: CommandResult,
    *,
    repo_id: str,
    repo_name: str,
) -> None:
    """Map a clone :class:`CommandResult` to the typed error hierarchy.

    - ``exit_code == 0``  → return (success).
    - ``exit_code == -1`` → :class:`RepoCloneTransientError`
      (sandbox-side runner failure — DBOS retries).
    - ``exit_code > 0``   → :class:`RepoCloneError` (real ``git``
      failure: bad token, missing repo, transport error — final).
    """
    if result.exit_code == 0:
        return
    tail = truncate_diff_output(result.stderr or result.stdout or "")
    if result.exit_code == -1:
        raise RepoCloneTransientError(
            repo_id=repo_id,
            repo_name=repo_name,
            cause=tail or "sandbox command runner failure",
        )
    raise RepoCloneError(
        repo_id=repo_id,
        repo_name=repo_name,
        exit_code=result.exit_code,
        output_tail=tail,
    )


@DBOS.step(
    retries_allowed=True,
    max_attempts=3,
    should_retry=_SHOULD_RETRY_TRANSIENT,
)
async def clone_repo_step(
    *,
    sandbox_id: str,
    sandbox_name: str,
    user_id: str,
    repo_id: str,
    repo_owner: str,
    repo_name: str,
    pr_number: int,
    github_installation_id: int,
) -> None:
    """Durable step: clone the repo into the review sandbox.

    Sequence:

    1. Mint an installation token for ``github_installation_id``.
    2. Reconnect to the sandbox by id.
    3. Create the workspace folder and remove any stale clone directory
       (keeps the step idempotent across a DBOS retry).
    4. ``git clone`` the default branch with the token via ``envs``.
    5. Best-effort fetch of ``refs/pull/{pr_number}/head`` so fork-PR
       heads are diffable; a failed fetch is logged, not fatal (the
       diff step's ``git fetch origin`` remains the catch-all).

    The sandbox is paused in a ``finally`` (the workflow's own
    ``finally`` destroys it with
    :func:`app.services.review.steps.stop_sandbox.kill_sandbox_step`).

    Raises:
        RepoCloneTransientError: token mint / reconnect / runner dropout
            failed. Transient — DBOS retries.
        RepoCloneError: ``git clone`` itself failed. Final — not retried.
    """
    try:
        token = await mint_installation_token(github_installation_id)
    except Exception as exc:
        log.warning(
            "clone_repo_step: token mint failed (will retry): "
            "installation_id=%s repo_id=%s cause=%s: %s",
            github_installation_id,
            repo_id,
            type(exc).__name__,
            exc,
        )
        raise RepoCloneTransientError(
            repo_id=repo_id,
            repo_name=repo_name,
            cause=f"installation token mint failed: {type(exc).__name__}: {exc}",
        ) from exc

    spec = _e2b_spec()
    try:
        sandbox = await E2BSandbox.connect(
            sandbox_id=sandbox_id,
            sandbox_name=sandbox_name,
            repo_id=repo_id,
            user_id=user_id,
            spec=spec,
            timeout=60 * 60,
            api_key=spec.api_key,
        )
    except Exception as exc:
        log.warning(
            "clone_repo_step: sandbox reconnect failed (will retry): "
            "user_id=%s repo_id=%s sandbox_id=%s cause=%s: %s",
            user_id,
            repo_id,
            sandbox_id,
            type(exc).__name__,
            exc,
        )
        raise RepoCloneTransientError(
            repo_id=repo_id,
            repo_name=repo_name,
            cause=f"sandbox reconnect failed: {type(exc).__name__}: {exc}",
        ) from exc

    repo_path = f"{workspace_path()}/{repo_name}"

    try:
        await sandbox.fs_create_folder(workspace_path())
        await sandbox.fs_delete(repo_path)

        clone = await sandbox.execute(
            build_review_clone_command(repo_owner=repo_owner, repo_name=repo_name),
            cwd=workspace_path(),
            envs={_TOKEN_ENV_VAR: token},
            timeout=CLONE_TIMEOUT_S,
        )
        check_clone_result(clone, repo_id=repo_id, repo_name=repo_name)

        fetch = await sandbox.execute(
            build_pr_ref_fetch_command(pr_number=pr_number),
            cwd=repo_path,
            timeout=PR_REF_FETCH_TIMEOUT_S,
        )
        if fetch.exit_code != 0:
            log.warning(
                "clone_repo_step: pr ref fetch failed (continuing): "
                "pr_number=%s exit_code=%s stderr=%s",
                pr_number,
                fetch.exit_code,
                fetch.stderr,
            )
    finally:
        try:
            await sandbox.stop()
        except Exception:
            log.exception(
                "clone_repo_step: failed to stop sandbox after clone: sandbox_id=%s",
                sandbox_id,
            )

    log.info(
        "clone_repo_step: ok repo_id=%s repo_name=%s sandbox_id=%s",
        repo_id,
        repo_name,
        sandbox_id,
    )


__all__ = [
    "build_pr_ref_fetch_command",
    "build_review_clone_command",
    "check_clone_result",
    "clone_repo_step",
]