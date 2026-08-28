"""Agent tools for the review pipeline.

These tools are bound to a specific review context (sandbox, PR number,
head SHA) and passed to the review deep-agent. The agent can call them
to read on-demand data that is too large to embed in the prompt, such
as the unified PR diff.

The per-file annotated chunks written by the split step into
``splitted_diffs/`` carry the visible LEFT/RIGHT gutter line numbers,
so the specialist subagents validate their ``(file, line, side)``
anchors directly against the chunk text they read.
"""

from __future__ import annotations

from deepagents.backends.protocol import ReadResult
from deepagents.backends.sandbox import BaseSandbox
from langchain_core.tools import BaseTool, tool

_REVIEW_DIFF_DIR_TEMPLATE = "/tmp/{pr_number}/{head_sha}"
"""Template of the in-sandbox directory holding the PR diff artefacts.

``file.diff`` (the raw unified diff), ``overview.md``, and
``splitted_diffs/`` (the per-file annotated chunks) live under this
directory. The path is shared with the prompt assembly in
:mod:`app.services.agent.service` (via :func:`getReviewDiffDirPath`)
so the tool and the prompt can never drift apart.
"""


def getReviewDiffDirPath(workDir: str, prNumber: int, headSha: str) -> str:
    """Return the in-sandbox directory holding the PR diff artefacts.

    Layout: ``/home/user/tmp/{pr_number}/{head_sha}/`` — ``file.diff``
    (the raw unified diff), ``overview.md``, and ``splitted_diffs/``
    (the per-file annotated chunks written by the split step).
    """
    return workDir + _REVIEW_DIFF_DIR_TEMPLATE.format(
        pr_number=prNumber, head_sha=headSha
    )


def makeGetDiffTool(
    sandbox: BaseSandbox,
    prNumber: int,
    headSha: str,
    workDir: str,
) -> BaseTool:
    """Return a ``get_diff`` tool that reads the PR diff from the sandbox.

    The diff is expected at
    ``/home/user/tmp/{pr_number}/{head_sha}/file.diff``.
    """
    path = f"{getReviewDiffDirPath(workDir=workDir, prNumber=prNumber , headSha=headSha)}/file.diff"

    @tool
    async def get_diff(limit: int, offset: int) -> ReadResult:
        """Read the PR diff from the sandbox."""
        return await sandbox.aread(file_path=path, limit=limit, offset=offset)

    return get_diff


__all__ = ["getReviewDiffDirPath", "makeGetDiffTool"]
