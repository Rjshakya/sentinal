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
   stays idempotent across a durable retry).

Fail-closed contract: any terminal install/index failure raises and
fails the run — v2 never reviews with a dead search tool.

Exit-code contract: ``0`` success on both commands; ``124``
(timeout) / ``-1`` (runner dropout) transient, and ``>0`` final for
the index. Pure helpers: :func:`buildInstallCommand` /
:func:`buildIndexCommand` (argv builders) and
:func:`parseIndexSummary` (stdout parser).
"""

from __future__ import annotations

import logging
import re
import shlex

from pydantic import BaseModel

from app.services.sandbox.e2b_template import CODEGRAPH_PCK_NAME
from app.services.sandbox.types import SandboxCtx
from app.utils.branded import CommitId, PRNumber, RepoId, RepoName, UserId
from app.utils.util import graph_db_path, repo_path
from app.workflows.review_v2.errors import (
    CodeGraphIndexError,
    CodeGraphInstallTransientError,
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


def buildInstallCommand() -> str:
    """Return the in-sandbox install command for the pinned CLI."""
    return f"pip install {shlex.quote(CODEGRAPH_PCK_NAME)}"


def buildIndexCommand(*, repoName: RepoName, db_path: str | None = None) -> str:
    """Return the in-sandbox index command for the checked-out tree.

    ``--overwrite`` keeps the worker idempotent across a durable retry;
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
        raise ValueError(f"no index summary in output: {truncateOutput(output)}")
    return CodeGraphIndexResult(
        files=int(match.group(1)),
        nodes=int(match.group(2)),
        edges=int(match.group(3)),
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
    """Install the codegraph CLI and index the repo tree.

    The published distribution comes from public PyPI, so no tokens
    are minted and nothing is uploaded. Returns the indexed counts so
    the workflow can record them. Fail-closed: the run fails instead
    of reviewing with a dead search tool.

    Raises:
        TransientReviewStepFailure: sandbox reconnect / runner dropout
            / pip transport flake failed.
        ReviewStepFailure: the install or the index failed terminally.
    """
    sandbox = await connectSandbox(sandboxCtx)
    if isinstance(sandbox, SandboxConnectError):
        raise TransientReviewStepFailure(sandbox)
    backend = asAsyncSandbox(sandbox)

    try:
        installed = await backend.aexecute(
            buildInstallCommand(), timeout=INSTALL_TIMEOUT_S
        )
    except Exception as exc:
        raise TransientReviewStepFailure(
            CodeGraphInstallTransientError(
                message=f"failed to run pip install: {type(exc).__name__}: {exc}",
                userId=userId,
                repoId=repoId,
            )
        ) from exc
    if installed.exit_code in (-1, 124):
        raise TransientReviewStepFailure(
            CodeGraphInstallTransientError(
                message=(
                    "sandbox command runner failure during pip install: "
                    f"{truncateOutput(installed.output) or 'no output'}"
                ),
                userId=userId,
                repoId=repoId,
            )
        )
    if installed.exit_code != 0:
        tail = truncateOutput(installed.output)
        raise TransientReviewStepFailure(
            CodeGraphInstallTransientError(
                message=f"pip install exited {installed.exit_code}: {tail}",
                userId=userId,
                repoId=repoId,
                exitCode=installed.exit_code,
                outputTail=tail,
            )
        )

    try:
        indexed = await backend.aexecute(
            buildIndexCommand(repoName=repoName, db_path=graph_db_path()),
            timeout=INDEX_TIMEOUT_S,
        )
    except Exception as exc:
        raise TransientReviewStepFailure(
            CodeGraphInstallTransientError(
                message=f"failed to run codegraph index: {type(exc).__name__}: {exc}",
                userId=userId,
                repoId=repoId,
            )
        ) from exc
    if indexed.exit_code in (-1, 124):
        raise TransientReviewStepFailure(
            CodeGraphInstallTransientError(
                message=(
                    "sandbox command runner failure during codegraph index: "
                    f"{truncateOutput(indexed.output) or 'no output'}"
                ),
                userId=userId,
                repoId=repoId,
            )
        )
    if indexed.exit_code != 0:
        tail = truncateOutput(indexed.output)
        raise ReviewStepFailure(
            CodeGraphIndexError(
                message=f"codegraph index exited {indexed.exit_code}: {tail}",
                userId=userId,
                repoId=repoId,
                prNumber=prNumber,
                headSha=headSha,
                exitCode=indexed.exit_code,
                outputTail=tail,
            )
        )

    try:
        result = parseIndexSummary(indexed.output)
    except ValueError as exc:
        raise ReviewStepFailure(
            CodeGraphIndexError(
                message=f"codegraph index summary unparseable: {exc}",
                userId=userId,
                repoId=repoId,
                prNumber=prNumber,
                headSha=headSha,
            )
        ) from exc

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
    "installCodeGraphAndIndexRepoStep",
    "parseIndexSummary",
]
