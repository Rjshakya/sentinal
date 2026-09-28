"""Install the codegraph CLI and index the PR-head tree, in-sandbox.

The v2 review agents explore the repo through the ``search_codegraph``
tool, which reads a codegraph database of the checked-out tree. This
step prepares that database inside the run's ephemeral sandbox, right
after :func:`app.workflows.review_v2.steps.clone_repo_v2.cloneRepoV2Step`
places the tree at the reviewed head SHA:

1. ``pip install`` the published ``sentinel-codegraph`` distribution
   (public PyPI — no tokens, no uploads), then
2. ``codegraph index`` the repo dir into the fixed run database
   (:func:`app.utils.util.graph_db_path`, ``--overwrite`` so the step
   stays idempotent across a DBOS retry).

Fail-closed contract: any terminal install/index failure raises and
fails the run — v2 never reviews with a dead search tool.

Exit-code contract: ``0`` success on both commands; ``124``
(timeout) / ``-1`` (runner dropout) transient — DBOS retries — and
``>0`` final for the index (a bad pin surfaces as a pip failure;
pip transport flakes are transient and capped by ``max_attempts``).

Layers per step file:

- :func:`buildInstallCommand` / :func:`buildIndexCommand` — pure
  argv builders.
- :func:`parseIndexSummary` — the pure stdout parser (``indexed N
  files, M nodes, K edges``).
- :func:`installCodeGraphAndIndexRepo` — the value-returning worker:
  takes the sandbox handle as an explicit input, returns
  :class:`CodeGraphIndexResult` or a typed error value.
- :func:`installCodeGraphAndIndexRepoStep` — the DBOS step edge:
  connects the sandbox, runs the worker, and raises for retryable /
  final failures. Returns the result so the workflow can record the
  indexed counts.
"""

from __future__ import annotations

import logging
import re
import shlex
from typing import Protocol, cast

from dbos import DBOS
from deepagents.backends.protocol import ExecuteResponse
from deepagents.backends.sandbox import BaseSandbox
from pydantic import BaseModel

from app.services.sandbox.e2b_template import CODEGRAPH_PCK_NAME
from app.services.sandbox.errors import SandboxProviderError
from app.services.sandbox.service import getProvider
from app.services.sandbox.types import SandboxCtx
from app.utils.branded import CommitId, PRNumber, RepoId, RepoName, UserId
from app.utils.util import graph_db_path, repo_path
from app.workflows.review_v2.errors import (
    CodeGraphIndexError,
    CodeGraphInstallError,
    CodeGraphInstallTransientError,
    ReviewStepFailure,
    SandboxConnectError,
    TransientReviewStepFailure,
    shouldRetry,
)

log = logging.getLogger(__name__)

INSTALL_TIMEOUT_S: int = 300
"""Upper bound on the in-sandbox ``pip install`` (wheel downloads)."""

INDEX_TIMEOUT_S: int = 600
"""Upper bound on the in-sandbox ``codegraph index`` (scales with repo)."""

_INDEX_SUMMARY_RE: re.Pattern[str] = re.compile(
    r"(?:indexed|scanned)\s+(\d+)\s+files?,\s+(\d+)\s+nodes?,\s+(\d+)\s+edges?"
)
"""Matches the codegraph summary line (optional ``(N skipped)`` suffix ignored)."""


class CodeGraphIndexResult(BaseModel):
    """Outcome of :func:`installCodeGraphAndIndexRepo`: the tree is indexed."""

    files: int
    nodes: int
    edges: int


class _AsyncSandboxBackend(Protocol):
    """The async sandbox surface the codegraph worker runs on."""

    async def aexecute(
        self,
        command: str,
        *,
        timeout: int | None = None,
    ) -> ExecuteResponse: ...


def _truncateOutput(raw: str, *, maxChars: int = 500) -> str:
    """Trim a command's output tail for inclusion in an error."""
    return (raw or "").strip()[:maxChars]


def buildInstallCommand() -> str:
    """Return the in-sandbox install command for the pinned CLI."""
    return f"pip install {shlex.quote(CODEGRAPH_PCK_NAME)}"


def buildIndexCommand(*, repoName: RepoName, db_path: str | None = None) -> str:
    """Return the in-sandbox index command for the checked-out tree.

    ``--overwrite`` keeps the worker idempotent across a DBOS retry;
    the database path defaults to the fixed run constant both the step
    and the ``search_codegraph`` tool recompute; pass ``db_path`` to
    target another database (e.g. the CLI default in live tests).
    """
    db: str = db_path or graph_db_path()
    return (
        f"codegraph index {shlex.quote(repo_path(str(repoName)))} "
        f"--db {shlex.quote(db)} --overwrite"
    )


def parseIndexSummary(output: str) -> CodeGraphIndexResult:
    """Parse the ``indexed N files, M nodes, K edges`` summary line.

    Raises:
        ValueError: no summary line in ``output``.
    """
    match: re.Match[str] | None = _INDEX_SUMMARY_RE.search(output)
    if match is None:
        raise ValueError(f"no index summary in output: {_truncateOutput(output)}")
    return CodeGraphIndexResult(
        files=int(match.group(1)),
        nodes=int(match.group(2)),
        edges=int(match.group(3)),
    )


async def _connectCodeGraphSandbox(sandboxCtx: SandboxCtx):
    """Reconnect to the run's sandbox by id (or create when unset)."""
    provider = getProvider(sandboxCtx.providerId)
    sandbox = await provider(ctx=sandboxCtx).create()
    if isinstance(sandbox, SandboxProviderError):
        return SandboxConnectError(
            message=sandbox.message,
            userId=sandbox.userId,
            repoId=sandbox.repoId,
        )
    return sandbox


async def installCodeGraphAndIndexRepo(
    sandbox: BaseSandbox,
    *,
    userId: UserId,
    repoId: RepoId,
    repoName: RepoName,
    prNumber: PRNumber,
    headSha: CommitId,
) -> CodeGraphIndexResult | CodeGraphInstallTransientError | CodeGraphIndexError:
    """Install the codegraph CLI and index the PR-head tree.

    Two sequential commands (install, then index), each exit-gated.
    Fail-closed: any terminal failure folds into a final error value —
    v2 never reviews with a dead search tool.
    """
    backend = cast(_AsyncSandboxBackend, sandbox)

    try:
        installed = await backend.aexecute(
            buildInstallCommand(), timeout=INSTALL_TIMEOUT_S
        )
    except Exception as exc:
        return CodeGraphInstallTransientError(
            message=f"failed to run pip install: {type(exc).__name__}: {exc}",
            userId=userId,
            repoId=repoId,
        )
    if installed.exit_code in (-1, 124):
        return CodeGraphInstallTransientError(
            message=(
                "sandbox command runner failure during pip install: "
                f"{_truncateOutput(installed.output) or 'no output'}"
            ),
            userId=userId,
            repoId=repoId,
        )
    if installed.exit_code != 0:
        tail = _truncateOutput(installed.output)
        return CodeGraphInstallTransientError(
            message=f"pip install exited {installed.exit_code}: {tail}",
            userId=userId,
            repoId=repoId,
            exitCode=installed.exit_code,
            outputTail=tail,
        )

    try:
        indexed = await backend.aexecute(
            buildIndexCommand(repoName=repoName, db_path=graph_db_path()),
            timeout=INDEX_TIMEOUT_S,
        )
    except Exception as exc:
        return CodeGraphInstallTransientError(
            message=f"failed to run codegraph index: {type(exc).__name__}: {exc}",
            userId=userId,
            repoId=repoId,
        )
    if indexed.exit_code in (-1, 124):
        return CodeGraphInstallTransientError(
            message=(
                "sandbox command runner failure during codegraph index: "
                f"{_truncateOutput(indexed.output) or 'no output'}"
            ),
            userId=userId,
            repoId=repoId,
        )
    if indexed.exit_code != 0:
        tail = _truncateOutput(indexed.output)
        return CodeGraphIndexError(
            message=f"codegraph index exited {indexed.exit_code}: {tail}",
            userId=userId,
            repoId=repoId,
            prNumber=prNumber,
            headSha=headSha,
            exitCode=indexed.exit_code,
            outputTail=tail,
        )

    try:
        return parseIndexSummary(indexed.output)
    except ValueError as exc:
        return CodeGraphIndexError(
            message=f"codegraph index summary unparseable: {exc}",
            userId=userId,
            repoId=repoId,
            prNumber=prNumber,
            headSha=headSha,
        )


@DBOS.step(
    retries_allowed=True,
    max_attempts=3,
    should_retry=shouldRetry,
    backoff_rate=2,
)
async def installCodeGraphAndIndexRepoStep(
    *,
    sandboxCtx: SandboxCtx,
    userId: UserId,
    repoId: RepoId,
    repoName: RepoName,
    prNumber: PRNumber,
    headSha: CommitId,
) -> CodeGraphIndexResult:
    """Durable step: install the codegraph CLI and index the repo tree.

    The published distribution comes from public PyPI, so no tokens
    are minted and nothing is uploaded. Returns the indexed counts so
    the workflow can record them.

    Raises:
        TransientReviewStepFailure: sandbox reconnect / runner dropout
            / pip transport flake failed. DBOS retries.
        ReviewStepFailure: the install or the index failed terminally.
            Final — the run fails instead of reviewing with a dead
            search tool.
    """
    sandbox = await _connectCodeGraphSandbox(sandboxCtx)
    if isinstance(sandbox, SandboxConnectError):
        raise TransientReviewStepFailure(sandbox)

    result = await installCodeGraphAndIndexRepo(
        sandbox,
        userId=userId,
        repoId=repoId,
        repoName=repoName,
        prNumber=prNumber,
        headSha=headSha,
    )
    if isinstance(result, CodeGraphInstallTransientError):
        raise TransientReviewStepFailure(result)
    if isinstance(result, (CodeGraphInstallError, CodeGraphIndexError)):
        raise ReviewStepFailure(result)

    log.info(
        "codegraph_index_step: ok repo_id=%s repo_name=%s sandbox_id=%s "
        "files=%d nodes=%d edges=%d",
        repoId,
        repoName,
        sandboxCtx.sandboxId,
        result.files,
        result.nodes,
        result.edges,
    )
    return result


__all__ = [
    "CodeGraphIndexResult",
    "buildIndexCommand",
    "buildInstallCommand",
    "installCodeGraphAndIndexRepo",
    "installCodeGraphAndIndexRepoStep",
    "parseIndexSummary",
]
