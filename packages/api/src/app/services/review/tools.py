"""Agent tools for the review pipeline.

These tools are bound to a specific review context (sandbox, PR number, head
SHA) and passed to the review deep-agent. The agent can call them to read
on-demand data that is too large to embed in the prompt, such as the unified
PR diff.

Comment-line validation is no longer a dedicated tool. The HunkMap is written
to ``diff.json`` inside the sandbox by :func:`app.services.review.diff.parse_and_write_diff_json`,
and the specialist subagents are told (in their system prompts) to ``read_file``
that JSON, check the ``(file, line, side)`` anchor against
``files[file_name][side]``, and re-anchor to the nearest in-bounds line in
the same hunk when the original anchor is not present. The server-side
:func:`app.services.review.hunk_map.filter_drafts` remains the final
backstop.
"""

from __future__ import annotations

from langchain_core.tools import BaseTool, tool

from app.core.sandbox import BaseSandbox


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


__all__: list[str] = ["make_get_diff_tool"]
