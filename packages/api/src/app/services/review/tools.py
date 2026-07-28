"""Agent tools for the review pipeline.

These tools are bound to a specific review context (sandbox, PR number, head
SHA) and passed to the review deep-agent. The agent can call them to read
on-demand data that is too large to embed in the prompt, such as the unified
PR diff.

The second tool, ``verify_comment_line``, is bound to the parsed
:data:`HunkMap` so the agent can self-validate ``(file, line, side)``
anchors before emitting :class:`CodeCommentDraft` entries.
"""

from __future__ import annotations

from langchain_core.tools import BaseTool, tool

from app.core.sandbox import BaseSandbox
from app.services.review.hunk_map import HunkMap


def make_get_diff_tool(
    sandbox: BaseSandbox,
    pr_number: int,
    head_sha: str,
) -> BaseTool:
    """Return a ``get_diff`` tool that reads the PR diff from the sandbox.

    The diff is expected at ``/home/user/tmp/{pr_number}/{head_sha}/file.diff``,
    which is the path written by :func:`app.services.review.diff.fetch_diff`.
    """
    path = f"/home/user/tmp/{pr_number}/{head_sha}/file.diff"

    @tool
    async def get_diff() -> str:
        """Read the PR diff from the sandbox."""
        return await sandbox.read_text(path)

    return get_diff


def make_verify_comment_line_tool(
    *,
    hunk_map: HunkMap,
) -> BaseTool:
    """Return a ``verify_comment_line`` tool bound to a parsed :data:`HunkMap`.

    The tool answers a single question: "is this anchor — ``(file, line,
    side)`` — one that GitHub will accept on this PR's diff?". It is the
    primary mechanism by which the review agent self-validates before
    emitting a :class:`CodeCommentDraft`.

    The output is a plain boolean. The agent is told in its prompt:
    "if the tool returns ``valid=true``, emit the draft; if ``valid=false``,
    drop the comment". No suggestion, no reason, no extra fields.

    The :data:`HunkMap` is bound at tool-creation time so every call is a
    constant-time set lookup.
    """
    @tool
    async def verify_comment_line(file: str, line: int, side: str) -> dict[str, bool]:
        """Return ``{"valid": bool}``.

        ``file`` is the path as it appears in the diff header
        (e.g. ``"src/app/routers/ai.py"``). ``line`` is the 1-based
        line number on ``side`` (``"RIGHT"`` = new file, ``"LEFT"`` =
        old file). Returns ``valid=true`` iff GitHub will accept this
        anchor as a review comment.
        """
        file_entry = hunk_map.get(file)
        if file_entry is None:
            return {"valid": False}
        side_set = file_entry.get(side)
        if side_set is None:
            return {"valid": False}
        return {"valid": line in side_set}

    return verify_comment_line


__all__: list[str] = ["make_get_diff_tool", "make_verify_comment_line_tool"]
