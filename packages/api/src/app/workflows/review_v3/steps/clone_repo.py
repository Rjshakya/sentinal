"""Clone the repo and check out the PR head, fail-closed.

Sequential shell over one reconnected backend: ensure the sentinel
root, drop any stale clone, ``git clone`` the default branch, fetch
``refs/pull/{pr}/head`` (uniform for same-repo and fork PRs), gate on
the head SHA resolving locally, detached checkout, verify ``HEAD``.
Any checkout-stage refusal fails the run — v3 never reviews a
half-built tree. The token travels as an inline value inside the
sandbox command only, never in host logs.
"""

from __future__ import annotations

import shlex

from app.services.sandbox.errors import SandboxProviderError
from app.services.sandbox.service import getProvider
from app.services.sandbox.types import BaseSandbox, ExecuteResponse, SandboxCtx
from app.utils.branded import CommitId, PRNumber, RepoName, RepoOwner, UserId
from app.utils.sandbox_fs import getRepoDir, sentinelRoot
from app.workflows.review_v3.errors import CloneError
from app.workflows.review_v3.types import CloneResult

_CLONE_TIMEOUT_S = 300
_FETCH_TIMEOUT_S = 120
_LOCAL_TIMEOUT_S = 60
_ERROR_CHARS = 500


def _tail(output: str) -> str:
    """Last meaningful chars of sandbox output for error values."""
    return output.strip()[-_ERROR_CHARS:]


async def _run(
    backend: BaseSandbox, command: str, *, timeoutS: int
) -> ExecuteResponse | CloneError:
    """Run one command; transport failure folds into a retryable error."""
    try:
        return await backend.aexecute(command, timeout=timeoutS)
    except Exception as exc:
        return CloneError(
            message=f"sandbox exec raised {type(exc).__name__}: {exc}",
            retryable=True,
        )


async def cloneRepo(
    *,
    sandboxCtx: SandboxCtx,
    userId: UserId,
    repoOwner: RepoOwner,
    repoName: RepoName,
    prNumber: PRNumber,
    headSha: CommitId,
    accessToken: str | None,
) -> CloneResult | CloneError:
    """Clone + fetch PR ref + detached checkout + verify, atomically."""
    if not str(headSha):
        raise ValueError("headSha must be non-empty")
    try:
        provider = getProvider(sandboxCtx.providerId)
    except Exception as exc:
        return CloneError(
            message=f"unknown sandbox provider: {type(exc).__name__}: {exc}",
            retryable=True,
        )
    try:
        made = await provider(ctx=sandboxCtx).create()
    except Exception as exc:
        return CloneError(
            message=f"sandbox reconnect raised {type(exc).__name__}: {exc}",
            retryable=True,
        )
    if isinstance(made, SandboxProviderError):
        return CloneError(
            message=f"sandbox reconnect failed: {made.message}", retryable=True
        )
    backend: BaseSandbox = made

    owner = str(repoOwner)
    name = str(repoName)
    sha = str(headSha)
    pr = int(prNumber)
    repoDir = getRepoDir(name)

    root = await _run(
        backend, f"mkdir -p {shlex.quote(sentinelRoot())}", timeoutS=_LOCAL_TIMEOUT_S
    )
    if isinstance(root, CloneError):
        return root
    if root.exit_code != 0:
        return CloneError(message=f"mkdir sentinel root failed: {_tail(root.output)}")

    swept = await _run(
        backend, f"rm -rf {shlex.quote(repoDir)}", timeoutS=_LOCAL_TIMEOUT_S
    )
    if isinstance(swept, CloneError):
        return swept
    if swept.exit_code != 0:
        return CloneError(message=f"stale clone removal failed: {_tail(swept.output)}")

    if accessToken:
        url = f"https://x-access-token:{accessToken}@github.com/{owner}/{name}.git"
    else:
        url = f"https://github.com/{owner}/{name}.git"
    cloned = await _run(
        backend,
        f"git clone --quiet {shlex.quote(url)} {shlex.quote(repoDir)}",
        timeoutS=_CLONE_TIMEOUT_S,
    )
    if isinstance(cloned, CloneError):
        return cloned
    if cloned.exit_code != 0:
        return CloneError(message=f"git clone failed: {_tail(cloned.output)}")

    fetched = await _run(
        backend,
        f"git -C {shlex.quote(repoDir)} fetch origin "
        f"refs/pull/{pr}/head:refs/remotes/origin/pr-{pr}",
        timeoutS=_FETCH_TIMEOUT_S,
    )
    if isinstance(fetched, CloneError):
        return fetched
    if fetched.exit_code != 0:
        return CloneError(
            message=f"pr ref fetch failed: {_tail(fetched.output)}",
            retryable=True,
        )

    gate = await _run(
        backend,
        f"git -C {shlex.quote(repoDir)} cat-file -e {shlex.quote(sha)}",
        timeoutS=_LOCAL_TIMEOUT_S,
    )
    if isinstance(gate, CloneError):
        return gate
    if gate.exit_code != 0:
        return CloneError(
            message="gate: head SHA not present locally after fetch"
        )

    checkout = await _run(
        backend,
        f"git -C {shlex.quote(repoDir)} checkout --detach {shlex.quote(sha)}",
        timeoutS=_LOCAL_TIMEOUT_S,
    )
    if isinstance(checkout, CloneError):
        return checkout
    if checkout.exit_code != 0:
        return CloneError(message=f"checkout failed: {_tail(checkout.output)}")

    verify = await _run(
        backend,
        f"git -C {shlex.quote(repoDir)} rev-parse HEAD",
        timeoutS=_LOCAL_TIMEOUT_S,
    )
    if isinstance(verify, CloneError):
        return verify
    actual = verify.output.strip()
    if verify.exit_code != 0 or actual != sha:
        return CloneError(
            message=f"verify: HEAD is {actual!r}, want {sha!r}"
        )
    return CloneResult(repoDir=repoDir, headSha=sha)


__all__ = ["CloneResult", "cloneRepo"]
