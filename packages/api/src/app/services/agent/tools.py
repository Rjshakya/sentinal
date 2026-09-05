"""Diff-dir path helper for the review pipeline.

The review agents get **no custom tools**: their diff context comes
strictly from the ``overview.md`` and ``splitted_diffs/`` artefacts,
which they read with the deepagents backend's built-in ``read_file`` /
``ls`` tools. This module only provides the shared in-sandbox path of
that directory so the user prompt and the pipeline steps can never
drift apart.
"""

from __future__ import annotations

_REVIEW_DIFF_DIR_TEMPLATE = "/tmp/{pr_number}/{head_sha}"
"""Template of the in-sandbox directory holding the PR diff artefacts.

``file.diff`` (the raw unified diff, consumed by the split step),
``overview.md``, and ``splitted_diffs/`` (the per-file annotated
chunks) live under this directory. The path is shared with the prompt
assembly in :mod:`app.services.agent.service` (via
:func:`getReviewDiffDirPath`) so the tool and the prompt can never
drift apart.
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


__all__ = ["getReviewDiffDirPath"]