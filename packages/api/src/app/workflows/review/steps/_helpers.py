"""Shared pure helpers for the review workflow steps.

Module-private (leading underscore on the file name) because nothing
outside the review workflow package needs these:

- :func:`connectSandbox` — the single reconnect-by-id helper: builds
  the provider from a :class:`SandboxCtx` and returns the LangChain
  sandbox backend, or a :class:`SandboxConnectError` value. Every step
  that touches the sandbox after the create step uses it.
- :func:`getReviewDiffDirPath` / :func:`getRepoPath` — the in-sandbox
  layout helpers shared by the diff, split, and agent steps (kept in
  lockstep with :func:`app.services.agent.tools.getReviewDiffDirPath`).
- :func:`truncateOutput` — trims a command's output tail for inclusion
  in an error message.

No logging, no DBOS, no raising: every function returns a value.
"""

from __future__ import annotations

from typing import Protocol, cast

from deepagents.backends.protocol import ExecuteResponse, FileUploadResponse
from deepagents.backends.sandbox import BaseSandbox

from app.services.sandbox.errors import SandboxProviderError
from app.services.sandbox.service import getProvider
from app.services.sandbox.types import SandboxCtx
from app.utils.util import repo_path
from app.workflows.review.errors import SandboxConnectError


class AsyncSandboxBackend(Protocol):
    """The async sandbox surface the review steps run on.

    ``BaseSandbox`` declares the sync ``execute`` / ``upload_files``
    and protocol-level async variants (``aexecute`` /
    ``aupload_files``) that concrete backends implement. The review
    pipeline runs inside an event loop, so it always uses the async
    variants; this protocol names exactly that surface.
    """

    async def aexecute(
        self,
        command: str,
        *,
        timeout: int | None = None,
    ) -> ExecuteResponse: ...

    async def aupload_files(
        self,
        files: list[tuple[str, bytes]],
    ) -> list[FileUploadResponse]: ...


def asAsyncSandbox(sandbox: BaseSandbox) -> AsyncSandboxBackend:
    """Narrow a :class:`BaseSandbox` to its async surface."""
    return cast(AsyncSandboxBackend, sandbox)


def truncateOutput(raw: str, *, maxChars: int = 500) -> str:
    """Trim a command's output tail for inclusion in an error."""
    cleaned = (raw or "").strip()
    return cleaned[:maxChars]


def getRepoPath(repoName: str) -> str:
    """Return the in-sandbox path of the cloned ``repoName``."""
    return repo_path(repoName)


def getReviewDiffDirPath(prNumber: int, headSha: str) -> str:
    """Return the in-sandbox directory holding the PR diff artefacts.

    Layout: ``/home/user/tmp/{pr_number}/{head_sha}/`` — ``file.diff``
    (the raw unified diff), ``overview.md``, and ``splitted_diffs/``
    (the per-file annotated chunks). Mirrors
    :func:`app.services.agent.tools.getReviewDiffDirPath` with the
    default root path.
    """
    return f"/home/user/tmp/{prNumber}/{headSha}"


async def connectSandbox(sandboxCtx: SandboxCtx) -> BaseSandbox | SandboxConnectError:
    """Reconnect to the run's sandbox by id (or create when unset).

    The provider's ``create()`` connects by ``sandboxCtx.sandboxId``
    when set and creates a fresh sandbox otherwise (writing the id back
    onto the ctx). Provider failures fold into a
    :class:`SandboxConnectError` value; callers decide at their edge.
    """
    provider = getProvider(sandboxCtx.providerId)
    sandbox = await provider(ctx=sandboxCtx).create()
    if isinstance(sandbox, SandboxProviderError):
        return SandboxConnectError(
            message=sandbox.message,
            userId=sandbox.userId,
            repoId=sandbox.repoId,
        )
    return sandbox


__all__ = [
    "AsyncSandboxBackend",
    "asAsyncSandbox",
    "connectSandbox",
    "getRepoPath",
    "getReviewDiffDirPath",
    "truncateOutput",
]