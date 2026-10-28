"""Install the codegraph CLI and index the PR-head tree, in-sandbox.

The pi agents explore the repo through their own read tools; the
codegraph database backs graph-first blast-radius checks. Two
sequential commands: ``pip install`` the published distribution
(public PyPI, no tokens), then ``codegraph index`` the checked-out
tree ``--overwrite`` (idempotent across retries). Fail-closed: a dead
search index fails the run instead of reviewing without it.
"""

from __future__ import annotations

import re
import shlex

from app.services.sandbox.e2b_template import CODEGRAPH_PCK_NAME
from app.services.sandbox.errors import SandboxProviderError
from app.services.sandbox.service import getProvider
from app.services.sandbox.types import BaseSandbox, SandboxCtx
from app.utils.branded import RepoName
from app.utils.sandbox_fs import getRepoDir
from app.utils.util import graph_db_path
from app.workflows.review_v3.errors import IndexError
from app.workflows.review_v3.types import IndexResult

_INSTALL_TIMEOUT_S = 300
_INDEX_TIMEOUT_S = 600
_ERROR_CHARS = 500

_INDEX_RE: re.Pattern[str] = re.compile(
    r"indexed\s+(\d+)\s+files?,\s+(\d+)\s+nodes?,\s+(\d+)\s+edges?"
)


async def indexCode(
    *, sandboxCtx: SandboxCtx, repoName: RepoName
) -> IndexResult | IndexError:
    """Pip-install the CLI and index the checked-out tree."""
    try:
        provider = getProvider(sandboxCtx.providerId)
    except Exception as exc:
        return IndexError(
            message=f"unknown sandbox provider: {type(exc).__name__}: {exc}",
            retryable=True,
        )
    try:
        made = await provider(ctx=sandboxCtx).create()
    except Exception as exc:
        return IndexError(
            message=f"sandbox reconnect raised {type(exc).__name__}: {exc}",
            retryable=True,
        )
    if isinstance(made, SandboxProviderError):
        return IndexError(
            message=f"sandbox reconnect failed: {made.message}", retryable=True
        )
    backend: BaseSandbox = made

    try:
        installed = await backend.aexecute(
            f"pip install {shlex.quote(CODEGRAPH_PCK_NAME)}",
            timeout=_INSTALL_TIMEOUT_S,
        )
    except Exception as exc:
        return IndexError(
            message=f"pip install raised {type(exc).__name__}: {exc}",
            retryable=True,
        )
    if installed.exit_code in (-1, 124):
        return IndexError(
            message="pip install: runner dropped the command", retryable=True
        )
    if installed.exit_code != 0:
        return IndexError(
            message=f"pip install exited {installed.exit_code}: "
            f"{installed.output.strip()[-_ERROR_CHARS:]}"
        )

    try:
        indexed = await backend.aexecute(
            f"codegraph index {shlex.quote(getRepoDir(str(repoName)))} "
            f"--db {shlex.quote(graph_db_path())} --overwrite",
            timeout=_INDEX_TIMEOUT_S,
        )
    except Exception as exc:
        return IndexError(
            message=f"codegraph index raised {type(exc).__name__}: {exc}",
            retryable=True,
        )
    if indexed.exit_code in (-1, 124):
        return IndexError(
            message="codegraph index: runner dropped the command", retryable=True
        )
    if indexed.exit_code != 0:
        return IndexError(
            message=f"codegraph index exited {indexed.exit_code}: "
            f"{indexed.output.strip()[-_ERROR_CHARS:]}"
        )
    match = _INDEX_RE.search(indexed.output)
    if match is None:
        return IndexError(message="codegraph index summary unparseable")
    return IndexResult(
        files=int(match.group(1)),
        nodes=int(match.group(2)),
        edges=int(match.group(3)),
    )


__all__ = ["IndexResult", "indexCode"]
