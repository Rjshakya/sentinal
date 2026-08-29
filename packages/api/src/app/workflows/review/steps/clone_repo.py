"""Clone the repo into the per-review sandbox.

The review pipeline is stateless: :func:`cloneRepoStep` clones the repo
at review time into the fresh sandbox created by
:func:`app.workflows.review.steps.create_sandbox.createSandboxStep`.

The clone and the PR-head ref fetch run as a small **in-sandbox Python
script** (:data:`_CLONE_SCRIPT_SRC`): the host runs the script source
inline via ``python3 -c`` with the installation token as an inline
``GITHUB_TOKEN=...`` env assignment in the same command — no files are
uploaded. The script reads the token from its environment, builds the
authenticated clone URL in-process, and hands it to ``git clone`` as an
argv entry; git redacts credentials in its own output. Every
interpolated command part is ``shlex.quote``d.

Exit-code contract: ``0`` success (stdout is the summary JSON parsed by
:func:`parseCloneResult`), ``124`` (timeout) / ``-1`` (runner dropout)
transient — DBOS retries — and ``>0`` script failure (business outcome —
the repo cannot be cloned; :class:`CloneError`).

Layers per step file:

- :func:`parseCloneResult` — the pure stdout parser.
- :func:`cloneRepo` — the value-returning worker: takes the token and
  sandbox handle as explicit inputs, returns :class:`CloneResult` or a
  typed error value.
- :func:`cloneRepoStep` — the DBOS step edge: mints the installation
  token, connects the sandbox, runs :func:`cloneRepo`, and raises for
  retryable / final failures.
"""

from __future__ import annotations

import json
import logging
import shlex

from dbos import DBOS
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

_RUN_TIMEOUT_S: int = CLONE_TIMEOUT_S + PR_REF_FETCH_TIMEOUT_S
"""Total wall-clock budget for the in-sandbox clone script run."""

_TOKEN_ENV_VAR: str = "GITHUB_TOKEN"
"""Env var name the inline env assignment exports for the script."""

_CLONE_SCRIPT_SRC: str = r'''"""Clone the repo's default branch and fetch the PR head ref.

In-sandbox script: the host runs this source inline via ``python3 -c``
with the installation token as an inline ``GITHUB_TOKEN=...`` env
assignment. It is never imported on the host, so it is fully
self-contained (stdlib only, no ``app.*`` imports).

Reads the installation token from the ``GITHUB_TOKEN`` environment
variable, builds the authenticated clone URL in-process, and passes it
to ``git clone`` as an argv entry — the token never appears in a
command string, and git redacts credentials in its own output.

Exit-code contract: ``0`` success (stdout is the summary JSON), ``>0``
failure (missing env, workspace prep, or ``git clone`` failed — stderr
carries the tail). The PR-head ref fetch is best-effort: a failure (or
its 120s timeout) is reported in the summary, never fatal.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys

_FETCH_TIMEOUT_S: int = 120


def _run(argv: list[str], *, timeout: int | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(argv, capture_output=True, text=True, timeout=timeout)


def main() -> int:
    parser = argparse.ArgumentParser(description="clone repo script")
    parser.add_argument("--owner", required=True, help="repo owner")
    parser.add_argument("--repo", required=True, help="repo name")
    parser.add_argument("--pr", type=int, required=True, help="PR number")
    parser.add_argument("--dest", required=True, help="clone destination path")
    parser.add_argument("--workspace", required=True, help="workspace dir path")
    args = parser.parse_args()

    token = os.environ.get("GITHUB_TOKEN", "")
    if not token:
        print("clone_repo.py: GITHUB_TOKEN not set", file=sys.stderr)
        return 1

    try:
        os.makedirs(args.workspace, exist_ok=True)
    except OSError as exc:
        print(f"clone_repo.py: workspace prep failed: {exc}", file=sys.stderr)
        return 1
    shutil.rmtree(args.dest, ignore_errors=True)

    url = f"https://x-access-token:{token}@github.com/{args.owner}/{args.repo}.git"
    clone = _run(["git", "clone", url, args.dest])
    if clone.returncode != 0:
        print(clone.stderr.strip() or "git clone failed", file=sys.stderr)
        return clone.returncode or 1

    pr_ref_fetch_failed = False
    try:
        fetch = _run(
            [
                "git",
                "-C",
                args.dest,
                "fetch",
                "origin",
                f"refs/pull/{args.pr}/head:refs/remotes/origin/pr-{args.pr}",
            ],
            timeout=_FETCH_TIMEOUT_S,
        )
        if fetch.returncode != 0:
            pr_ref_fetch_failed = True
            print(fetch.stderr.strip() or "git fetch failed", file=sys.stderr)
    except Exception as exc:
        pr_ref_fetch_failed = True
        print(f"clone_repo.py: pr ref fetch failed: {exc}", file=sys.stderr)

    print(json.dumps({"pr_ref_fetch_failed": pr_ref_fetch_failed}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
'''


def parseCloneResult(stdout: str) -> CloneResult:
    """Parse and validate the script's single stdout JSON line.

    Raises:
        ValueError: the stdout is not a single JSON object with a
            boolean ``pr_ref_fetch_failed``.
    """
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise ValueError(f"clone summary is not valid JSON: {stdout[:200]!r}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"clone summary is not a JSON object: {stdout[:200]!r}")

    pr_ref_fetch_failed = data.get("pr_ref_fetch_failed")
    if not isinstance(pr_ref_fetch_failed, bool):
        raise ValueError(
            f"clone summary has no boolean pr_ref_fetch_failed: {stdout[:200]!r}"
        )

    return CloneResult(prRefFetchFailed=pr_ref_fetch_failed)


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

    1. Run the in-sandbox script source inline (``python3 -c``) with
       the installation token as an inline ``GITHUB_TOKEN=...`` env
       assignment — no files are uploaded. The script creates the
       workspace folder, removes any stale clone directory (keeps the
       step idempotent across a DBOS retry), ``git clone``s the default
       branch with the token, and best-effort fetches
       ``refs/pull/{pr}/head`` so fork-PR heads are diffable. A failed
       fetch is reported on the result, not fatal.
    """
    backend = asAsyncSandbox(sandbox)
    repoPath = getRepoPath(repoName)
    workspace = workspace_path()
    command = (
        f"{_TOKEN_ENV_VAR}={shlex.quote(str(token))} "
        f"python3 -c {shlex.quote(_CLONE_SCRIPT_SRC)} "
        f"--owner {shlex.quote(str(repoOwner))} "
        f"--repo {shlex.quote(str(repoName))} "
        f"--pr {prNumber} "
        f"--dest {shlex.quote(repoPath)} "
        f"--workspace {shlex.quote(workspace)}"
    )

    try:
        result = await backend.aexecute(command, timeout=_RUN_TIMEOUT_S)
    except Exception as exc:
        return CloneTransientError(
            message=f"failed to run clone script: {type(exc).__name__}: {exc}",
            userId=userId,
            repoId=repoId,
        )

    if result.exit_code in (-1, 124):
        return CloneTransientError(
            message=(
                f"sandbox command runner failure: "
                f"{truncateOutput(result.output) or 'no output'}"
            ),
            userId=userId,
            repoId=repoId,
        )
    if result.exit_code != 0:
        tail = truncateOutput(result.output)
        return CloneError(
            message=f"clone script exited {result.exit_code}: {tail}",
            userId=userId,
            repoId=repoId,
            exitCode=result.exit_code,
            outputTail=tail,
        )

    try:
        return parseCloneResult(result.output.strip())
    except ValueError as exc:
        return CloneError(
            message=f"clone summary unparseable: {exc}",
            userId=userId,
            repoId=repoId,
        )


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
    service call), then passed to the sandbox as an inline env
    assignment in the clone command.

    Raises:
        TransientReviewStepFailure: token mint / sandbox reconnect /
            runner dropout failed. DBOS retries.
        ReviewStepFailure: the clone script failed. Final — not
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
    "cloneRepo",
    "cloneRepoStep",
    "parseCloneResult",
]
