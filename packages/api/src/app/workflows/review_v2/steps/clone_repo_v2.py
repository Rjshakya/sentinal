"""V2 clone: clone + PR-ref fetch + head checkout in one atomic script.

The v2 review pipeline is stateless: :func:`cloneRepoV2Step` prepares
the repo at review time inside the fresh sandbox created by
:func:`app.workflows.review_v2.steps.create_sandbox.createSandboxStep`.

Unlike the old default-branch-tree clone (best-effort ref fetch),
this step leaves the working tree **checked out at the reviewed head
SHA** — one in-sandbox Python script (:data:`_CLONE_V2_SCRIPT_SRC`)
runs clone → fetch → checkout → verify as a single invocation, so the
tree is never observed half-built:

- ``git clone`` the default branch with the installation token,
- ``fetch`` ``refs/pull/{pr}/head`` (works uniformly for same-repo
  and fork PRs — the head branch name is never trusted),
- ``checkout --detach {headSha}`` gated on the SHA resolving locally,
- verify ``rev-parse HEAD == headSha`` as the final gate.

Fail-closed contract: any checkout-stage refusal (fetch, gate,
checkout, verify) fails the run — v2 never reviews a half-built
tree. The clone and the PR-head fetch run with the installation
token as an inline ``GITHUB_TOKEN=...`` env assignment in the same
command — no files are uploaded. Every interpolated command part is
``shlex.quote``d.

Exit-code contract: ``0`` success (stdout is the summary JSON parsed
by :func:`parseCloneV2Result`), ``124`` (timeout) / ``-1`` (runner
dropout) transient, and ``>0`` script failure (business outcome — the
repo cannot be cloned).
"""

from __future__ import annotations

import json
import logging
import shlex

from pydantic import BaseModel

from app.services.github.repo.errors import GitHubRepoError
from app.services.github.repo.service import createRepoCtx, mintAccessToken
from app.services.sandbox.types import SandboxCtx
from app.utils.branded import (
    CommitId,
    InstallationId,
    PRNumber,
    RepoId,
    RepoName,
    RepoOwner,
    UserId,
)
from app.utils.util import repo_path, workspace_path
from app.workflows.review_v2.errors import (
    CheckoutError,
    CloneV2Error,
    CloneV2TransientError,
    ReviewStepFailure,
    SandboxConnectError,
    TransientReviewStepFailure,
)
from app.workflows.review_v2.steps._helpers import (
    asAsyncSandbox,
    connectSandbox,
    truncateOutput,
)

log = logging.getLogger(__name__)

CLONE_TIMEOUT_S: int = 300
"""Upper bound on the wall-clock duration of a single ``git clone``."""

PR_REF_FETCH_TIMEOUT_S: int = 120
"""Upper bound on the wall-clock duration of the PR-head ref fetch."""

CHECKOUT_TIMEOUT_S: int = 60
"""Upper bound on the local checkout + verify commands (no network)."""

_RUN_TIMEOUT_S: int = CLONE_TIMEOUT_S + PR_REF_FETCH_TIMEOUT_S + CHECKOUT_TIMEOUT_S
"""Total wall-clock budget for the in-sandbox clone script run."""

_TOKEN_ENV_VAR: str = "GITHUB_TOKEN"
"""Env var name the inline env assignment exports for the script."""

_CLONE_V2_SCRIPT_SRC: str = r'''"""Clone the repo and check out the PR head (atomic).

In-sandbox script: the host runs this source inline via ``python3 -c``
with the installation token as an inline ``GITHUB_TOKEN=...`` env
assignment. It is never imported on the host, so it is fully
self-contained (stdlib only, no ``app.*`` imports).

Reads the installation token from the ``GITHUB_TOKEN`` environment
variable, builds the authenticated clone URL in-process, and passes it
to ``git clone`` as an argv entry — the token never appears in a
command string, and git redacts credentials in its own output.

Sequence (single invocation — the tree is never observed half-built):

1. ``git clone`` the default branch (removes any stale dest first,
   so the step stays idempotent across a durable retry),
2. best-effort ``fetch`` of ``refs/pull/{pr}/head`` (uniform for
   same-repo and fork PRs),
3. ``checkout --detach {head_sha}`` — attempted only when the SHA
   resolves locally (``git cat-file -e`` gate),
4. verify ``git rev-parse HEAD == {head_sha}``.

Exit-code contract: ``0`` success (stdout is the summary JSON —
even when the fetch or checkout stage refused, which the summary
flags); ``>0`` failure (missing env, workspace prep, or ``git
clone`` failed — stderr carries the tail).
"""

import argparse
import json
import os
import shutil
import subprocess
import sys

_FETCH_TIMEOUT_S: int = 120
_CHECKOUT_TIMEOUT_S: int = 60


def _run(argv: list[str], *, timeout: int | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(argv, capture_output=True, text=True, timeout=timeout)


def main() -> int:
    parser = argparse.ArgumentParser(description="v2 clone + checkout script")
    parser.add_argument("--owner", required=True, help="repo owner")
    parser.add_argument("--repo", required=True, help="repo name")
    parser.add_argument("--pr", type=int, required=True, help="PR number")
    parser.add_argument("--head-sha", required=True, help="PR head SHA to check out")
    parser.add_argument("--dest", required=True, help="clone destination path")
    parser.add_argument("--workspace", required=True, help="workspace dir path")
    args = parser.parse_args()

    token = os.environ.get("GITHUB_TOKEN", "")
    if not token:
        print("clone_repo_v2.py: GITHUB_TOKEN not set", file=sys.stderr)
        return 1

    try:
        os.makedirs(args.workspace, exist_ok=True)
    except OSError as exc:
        print(f"clone_repo_v2.py: workspace prep failed: {exc}", file=sys.stderr)
        return 1
    shutil.rmtree(args.dest, ignore_errors=True)

    url = f"https://x-access-token:{token}@github.com/{args.owner}/{args.repo}.git"
    clone = _run(["git", "clone", url, args.dest])
    if clone.returncode != 0:
        print(clone.stderr.strip() or "git clone failed", file=sys.stderr)
        return clone.returncode or 1

    pr_ref_fetch_failed = False
    checkout_failed = False
    checkout_error: str | None = None
    checked_out_head: str | None = None

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
        print(f"clone_repo_v2.py: pr ref fetch failed: {exc}", file=sys.stderr)

    if not pr_ref_fetch_failed:
        gate = _run(["git", "-C", args.dest, "cat-file", "-e", args.head_sha])
        if gate.returncode != 0:
            checkout_failed = True
            checkout_error = "gate: head SHA not present locally after fetch"
        else:
            try:
                checkout = _run(
                    ["git", "-C", args.dest, "checkout", "--detach", args.head_sha],
                    timeout=_CHECKOUT_TIMEOUT_S,
                )
            except Exception as exc:
                checkout_failed = True
                checkout_error = f"checkout: {exc}"
                checkout = None
            if not checkout_failed and (checkout is None or checkout.returncode != 0):
                checkout_failed = True
                detail = (checkout.stderr.strip() if checkout is not None else "") or "git checkout failed"
                checkout_error = f"checkout: {detail}"
            if not checkout_failed:
                verify = _run(["git", "-C", args.dest, "rev-parse", "HEAD"])
                actual = verify.stdout.strip() if verify.returncode == 0 else ""
                if actual != args.head_sha:
                    checkout_failed = True
                    checkout_error = f"verify: HEAD is {actual!r}, want {args.head_sha!r}"
                else:
                    checked_out_head = actual
    else:
        checkout_failed = True
        checkout_error = "fetch: PR head ref unavailable, checkout skipped"

    if checkout_error is not None:
        print(f"clone_repo_v2.py: {checkout_error}", file=sys.stderr)
    print(
        json.dumps(
            {
                "pr_ref_fetch_failed": pr_ref_fetch_failed,
                "checkout_failed": checkout_failed,
                "checked_out_head": checked_out_head,
                "checkout_error": checkout_error,
            }
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
'''


def parseCloneV2Result(stdout: str) -> CloneV2Result:
    """Parse and validate the script's single stdout JSON line.

    Raises:
        ValueError: the stdout is not a single JSON object with a
            boolean ``pr_ref_fetch_failed``, a boolean
            ``checkout_failed``, a nullable-string ``checked_out_head``,
            and a nullable-string ``checkout_error``.
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
    checkout_failed = data.get("checkout_failed")
    if not isinstance(checkout_failed, bool):
        raise ValueError(
            f"clone summary has no boolean checkout_failed: {stdout[:200]!r}"
        )
    checked_out_head = data.get("checked_out_head")
    if checked_out_head is not None and not isinstance(checked_out_head, str):
        raise ValueError(
            f"clone summary has no nullable-string checked_out_head: {stdout[:200]!r}"
        )
    checkout_error = data.get("checkout_error")
    if checkout_error is not None and not isinstance(checkout_error, str):
        raise ValueError(
            f"clone summary has no nullable-string checkout_error: {stdout[:200]!r}"
        )

    return CloneV2Result(
        prRefFetchFailed=pr_ref_fetch_failed,
        checkoutFailed=checkout_failed,
        checkedOutHead=checked_out_head,
        checkoutError=checkout_error,
    )


class CloneV2Result(BaseModel):
    """Outcome of :func:`cloneRepoV2`: the tree is at the reviewed head.

    ``prRefFetchFailed=True`` can only occur together with
    ``checkoutFailed=True`` (the gate refuses checkout without the
    ref) — the worker converts any ``checkoutFailed`` summary into a
    :class:`CheckoutError`, so a returned result always describes a
    fully-known state: PR tree at ``checkedOutHead``.
    """

    prRefFetchFailed: bool = False
    checkoutFailed: bool = False
    checkedOutHead: str | None = None
    checkoutError: str | None = None


async def cloneRepoV2Step(
    *,
    sandboxCtx: SandboxCtx,
    userId: UserId,
    repoId: RepoId,
    repoOwner: RepoOwner,
    repoName: RepoName,
    prNumber: PRNumber,
    headSha: CommitId,
    githubInstallationId: InstallationId,
) -> CloneV2Result:
    """Clone the repo and check out the PR head, atomically.

    Mints the installation token, reconnects the sandbox, and runs the
    in-sandbox script source inline (``python3 -c``) with the token as
    an inline ``GITHUB_TOKEN=...`` env assignment — no files are
    uploaded. The script removes any stale clone directory, ``git
    clone``s the default branch, fetches ``refs/pull/{pr}/head``,
    checks out the head SHA detached, and verifies ``HEAD``.

    Fail-closed: any checkout-stage refusal fails the run — v2 never
    reviews a half-built tree.

    Raises:
        TransientReviewStepFailure: token mint / sandbox reconnect /
            runner dropout failed.
        ReviewStepFailure: the clone failed, or the PR-head checkout
            (or its verify gate) refused.
    """
    repoCtx = createRepoCtx(
        userId=userId,
        installationId=githubInstallationId,
        owner=repoOwner,
        repo=repoName,
    )
    token = await mintAccessToken(repoCtx)
    if isinstance(token, GitHubRepoError):
        log.warning(
            "clone_repo_v2_step: token mint failed (will retry): "
            "installation_id=%s repo_id=%s cause=%s",
            githubInstallationId,
            repoId,
            token.message,
        )
        raise TransientReviewStepFailure(
            CloneV2TransientError(
                message=f"installation token mint failed: {token.message}",
                userId=userId,
                repoId=repoId,
            )
        )

    sandbox = await connectSandbox(sandboxCtx)
    if isinstance(sandbox, SandboxConnectError):
        raise TransientReviewStepFailure(sandbox)

    backend = asAsyncSandbox(sandbox)
    dest = repo_path(str(repoName))
    workspace = workspace_path()
    command = (
        f"{_TOKEN_ENV_VAR}={shlex.quote(str(token))} "
        f"python3 -c {shlex.quote(_CLONE_V2_SCRIPT_SRC)} "
        f"--owner {shlex.quote(str(repoOwner))} "
        f"--repo {shlex.quote(str(repoName))} "
        f"--pr {prNumber} "
        f"--head-sha {shlex.quote(str(headSha))} "
        f"--dest {shlex.quote(dest)} "
        f"--workspace {shlex.quote(workspace)}"
    )

    try:
        result = await backend.aexecute(command, timeout=_RUN_TIMEOUT_S)
    except Exception as exc:
        raise TransientReviewStepFailure(
            CloneV2TransientError(
                message=f"failed to run clone script: {type(exc).__name__}: {exc}",
                userId=userId,
                repoId=repoId,
            )
        ) from exc

    if result.exit_code in (-1, 124):
        raise TransientReviewStepFailure(
            CloneV2TransientError(
                message=(
                    "sandbox command runner failure: "
                    f"{truncateOutput(result.output) or 'no output'}"
                ),
                userId=userId,
                repoId=repoId,
            )
        )
    if result.exit_code != 0:
        tail = truncateOutput(result.output)
        raise ReviewStepFailure(
            CloneV2Error(
                message=f"clone script exited {result.exit_code}: {tail}",
                userId=userId,
                repoId=repoId,
                exitCode=result.exit_code,
                outputTail=tail,
            )
        )

    try:
        summary = parseCloneV2Result(result.output.strip())
    except ValueError as exc:
        raise ReviewStepFailure(
            CloneV2Error(
                message=f"clone summary unparseable: {exc}",
                userId=userId,
                repoId=repoId,
            )
        ) from exc

    if summary.checkoutFailed:
        cause = summary.checkoutError or "checkout stage refused"
        raise ReviewStepFailure(
            CheckoutError(
                message=f"pr-head checkout failed: {cause}",
                userId=userId,
                repoId=repoId,
                prNumber=prNumber,
                headSha=headSha,
                cause=cause,
            )
        )

    if summary.prRefFetchFailed:
        log.warning(
            "clone_repo_v2_step: pr ref fetch failed (continuing): "
            "pr_number=%s repo_id=%s",
            prNumber,
            repoId,
        )
    log.info(
        "clone_repo_v2_step: ok repo_id=%s repo_name=%s sandbox_id=%s checked_out_head=%s",
        repoId,
        repoName,
        sandboxCtx.sandboxId,
        summary.checkedOutHead,
    )
    return summary


__all__ = [
    "CloneV2Result",
    "cloneRepoV2Step",
    "parseCloneV2Result",
]
