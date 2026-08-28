"""Clone the repo into the per-review sandbox.

The review pipeline is stateless: :func:`cloneRepoStep` clones the repo
at review time into the fresh sandbox created by
:func:`app.workflows.review.steps.create_sandbox.createSandboxStep`.

Security posture: the installation token is delivered to the sandbox as
a sourced env file (``upload_files`` writes it, so the token never
appears in a command string — the sandbox provider logs commands). The
clone command references ``${GITHUB_TOKEN}``, expanded by the sandbox
shell from the sourced file. Every interpolated command part is
``shlex.quote``d.

Exit-code contract: ``0`` success, ``124`` (timeout) / ``-1`` (runner
dropout) transient — DBOS retries — and ``>0`` final ``git`` failure
(:class:`CloneError`).

Layers per step file:

- :func:`buildCloneCommand` / :func:`buildPrRefFetchCommand` /
  :func:`cloneError` — pure builders and the exit-code mapper.
- :func:`cloneRepo` — the value-returning worker: takes the token and
  sandbox handle as explicit inputs, returns ``None`` or a typed error
  value.
- :func:`cloneRepoStep` — the DBOS step edge: mints the installation
  token, connects the sandbox, runs :func:`cloneRepo`, and raises for
  retryable / final failures.
"""

from __future__ import annotations

import logging
import shlex

from dbos import DBOS
from deepagents.backends.protocol import ExecuteResponse
from deepagents.backends.sandbox import BaseSandbox
from pydantic import BaseModel

from app.services.github.repo.errors import GitHubRepoError
from app.services.github.repo.service import createRepoCtx, mintAccessToken
from app.services.sandbox.types import SandboxCtx
from app.utils.branded import (
    AccessToken,
    InstallationId,
    PRNumber,
    RepoId,
    RepoName,
    RepoOwner,
    UserId,
)
from app.utils.util import workspace_path
from app.workflows.review.errors import (
    CloneError,
    CloneTransientError,
    ReviewStepFailure,
    SandboxConnectError,
    TransientReviewStepFailure,
    shouldRetry,
)
from app.workflows.review.steps._helpers import (
    asAsyncSandbox,
    connectSandbox,
    getRepoPath,
    truncateOutput,
)

log = logging.getLogger(__name__)

CLONE_TIMEOUT_S: int = 300
"""Upper bound on the wall-clock duration of a single ``git clone``."""

PR_REF_FETCH_TIMEOUT_S: int = 120
"""Upper bound on the wall-clock duration of the PR-head ref fetch."""

TOKEN_FILE: str = "/home/user/.sentinel_git_token"
"""Sandbox path of the sourced env file carrying the installation token.

Written via ``upload_files`` (file content is not command-logged) and
``source``d by the clone command so the token never appears in a
command string.
"""

_TOKEN_ENV_VAR: str = "GITHUB_TOKEN"
"""Env var name the sourced token file exports."""


def buildTokenFileContent(token: str) -> bytes:
    """The env-file payload exporting :data:`_TOKEN_ENV_VAR`."""
    return f"export {_TOKEN_ENV_VAR}={shlex.quote(token)}\n".encode("utf-8")


def buildCloneCommand(*, repoOwner: str, repoName: str) -> str:
    """Build the shell command cloning the repo's default branch.

    The token is referenced as ``${GITHUB_TOKEN}`` inside the HTTPS URL
    and resolved by the sandbox shell from the sourced
    :data:`TOKEN_FILE` — never interpolated into the command string.
    The destination path is shell-quoted.
    """
    url = (
        f"https://x-access-token:${{{_TOKEN_ENV_VAR}}}"
        f"@github.com/{repoOwner}/{repoName}.git"
    )
    dest = getRepoPath(repoName)
    return f". {shlex.quote(TOKEN_FILE)} && git clone {url} {shlex.quote(dest)}"


def buildPrRefFetchCommand(*, repoName: str, prNumber: int) -> str:
    """Build the shell command fetching the PR head ref (best-effort).

    ``refs/pull/{pr}/head`` is advertised for every open PR — same-repo
    and fork PRs alike — so the fetched head commit is diffable even
    when the PR branch was never pushed to origin.
    """
    repoPath = getRepoPath(repoName)
    return (
        f"cd {shlex.quote(repoPath)} && "
        f"git fetch origin refs/pull/{prNumber}/head:"
        f"refs/remotes/origin/pr-{prNumber}"
    )


def cloneError(
    result: ExecuteResponse,
    *,
    userId: UserId,
    repoId: RepoId,
    repoName: str,
) -> None | CloneError | CloneTransientError:
    """Map a clone :class:`ExecuteResponse` to the typed error hierarchy.

    ``0`` → ``None`` (success); ``124`` (timeout) / ``-1`` (runner
    dropout) → :class:`CloneTransientError` (DBOS retries); ``>0`` →
    :class:`CloneError` (real ``git`` failure — final).
    """
    if result.exit_code == 0:
        return None
    tail = truncateOutput(result.output)
    if result.exit_code in (-1, 124):
        return CloneTransientError(
            message=f"sandbox command runner failure: {tail or 'no output'}",
            userId=userId,
            repoId=repoId,
        )
    return CloneError(
        message=f"git clone failed (repo={repoName!r}): "
        f"git exited {result.exit_code}: {tail}",
        userId=userId,
        repoId=repoId,
        exitCode=result.exit_code,
        outputTail=tail,
    )


class CloneResult(BaseModel):
    """Outcome of :func:`cloneRepo`: the clone succeeded (possibly with
    a failed best-effort PR-ref fetch).

    ``prRefFetchFailed=True`` means the head ref was not fetched — the
    diff step's ``git fetch origin`` remains the catch-all, so the edge
    logs and continues.
    """

    prRefFetchFailed: bool = False


async def cloneRepo(
    sandbox: BaseSandbox,
    *,
    token: AccessToken,
    userId: UserId,
    repoId: RepoId,
    repoOwner: RepoOwner,
    repoName: RepoName,
    prNumber: PRNumber,
) -> CloneResult | CloneError | CloneTransientError:
    """Clone the default branch into the sandbox and fetch the PR head.

    Sequence:

    1. Upload the token env file (``upload_files`` — the token never
       appears in a command string).
    2. Create the workspace folder and remove any stale clone
       directory (keeps the step idempotent across a DBOS retry).
    3. ``git clone`` the default branch with the token via the sourced
       env file.
    4. Best-effort fetch of ``refs/pull/{pr}/head`` so fork-PR heads
       are diffable; a failed fetch is reported on the result, not
       fatal.
    """

    backend = asAsyncSandbox(sandbox)
    uploads = await backend.aupload_files(
        [(TOKEN_FILE, buildTokenFileContent(str(token)))]
    )
    upload_error = next((u.error for u in uploads if u.error is not None), None)
    if upload_error is not None:
        return CloneTransientError(
            message=f"failed to upload git token file to sandbox: {upload_error}",
            userId=userId,
            repoId=repoId,
        )

    repoPath = getRepoPath(repoName)
    workspace = workspace_path()

    setup = await backend.aexecute(
        f"mkdir -p {shlex.quote(workspace)} && rm -rf {shlex.quote(repoPath)}",
        timeout=60,
    )
    if setup.exit_code != 0:
        return CloneTransientError(
            message=f"workspace setup failed: {truncateOutput(setup.output)}",
            userId=userId,
            repoId=repoId,
        )

    clone = await backend.aexecute(
        buildCloneCommand(repoOwner=str(repoOwner), repoName=str(repoName)),
        timeout=CLONE_TIMEOUT_S,
    )
    error = cloneError(
        clone,
        userId=userId,
        repoId=repoId,
        repoName=str(repoName),
    )
    if error is not None:
        return error

    fetch = await backend.aexecute(
        buildPrRefFetchCommand(repoName=str(repoName), prNumber=prNumber),
        timeout=PR_REF_FETCH_TIMEOUT_S,
    )
    return CloneResult(prRefFetchFailed=fetch.exit_code != 0)


@DBOS.step(
    retries_allowed=True,
    max_attempts=3,
    should_retry=shouldRetry,
    backoff_rate=2,
)
async def cloneRepoStep(
    *,
    sandboxCtx: SandboxCtx,
    userId: UserId,
    repoId: RepoId,
    repoOwner: RepoOwner,
    repoName: RepoName,
    prNumber: PRNumber,
    githubInstallationId: InstallationId,
) -> None:
    """Durable step: clone the repo into the review sandbox.

    The installation token is minted at the edge via
    :func:`app.services.github.repo.mintAccessToken` (a value-returning
    service call), then delivered to the sandbox as a sourced env file.

    Raises:
        TransientReviewStepFailure: token mint / sandbox reconnect /
            runner dropout failed. DBOS retries.
        ReviewStepFailure: ``git clone`` itself failed. Final — not
            retried.
    """
    repoCtx = createRepoCtx(
        userId=userId,
        installationId=githubInstallationId,
        owner=repoOwner,
        repo=repoName,
    )
    token = await mintAccessToken(repoCtx)
    if isinstance(token, GitHubRepoError):
        err = CloneTransientError(
            message=f"installation token mint failed: {token.message}",
            userId=userId,
            repoId=repoId,
        )
        log.warning(
            "clone_repo_step: token mint failed (will retry): "
            "installation_id=%s repo_id=%s cause=%s",
            githubInstallationId,
            repoId,
            token.message,
        )
        raise TransientReviewStepFailure(err)

    sandbox = await connectSandbox(sandboxCtx)
    if isinstance(sandbox, SandboxConnectError):
        raise TransientReviewStepFailure(sandbox)

    result = await cloneRepo(
        sandbox,
        token=token,
        userId=userId,
        repoId=repoId,
        repoOwner=repoOwner,
        repoName=repoName,
        prNumber=prNumber,
    )
    if isinstance(result, CloneTransientError):
        raise TransientReviewStepFailure(result)
    if isinstance(result, CloneError):
        raise ReviewStepFailure(result)

    if result.prRefFetchFailed:
        log.warning(
            "clone_repo_step: pr ref fetch failed (continuing): "
            "pr_number=%s repo_id=%s",
            prNumber,
            repoId,
        )

    log.info(
        "clone_repo_step: ok repo_id=%s repo_name=%s sandbox_id=%s",
        repoId,
        repoName,
        sandboxCtx.sandboxId,
    )


__all__ = [
    "CloneResult",
    "buildCloneCommand",
    "buildPrRefFetchCommand",
    "buildTokenFileContent",
    "cloneError",
    "cloneRepo",
    "cloneRepoStep",
]
