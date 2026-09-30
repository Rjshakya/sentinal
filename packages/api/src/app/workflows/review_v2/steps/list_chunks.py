"""List the split-diff chunks: the host-side diff truth.

Connects to the sandbox and inventories ``splitted_diffs/`` without
reading any diff content: one ``grep -H '^### '`` over the chunk
headers for ``<chunk file>:### <real path>`` pairs. Returns the tiny
:class:`ChunkInventory` (real paths plus their exact on-disk diff
file names) — the diff text itself never crosses the sandbox
boundary.

Exit-code contract: ``0`` success; ``-1`` / ``124`` (runner dropout /
timeout) transient; any other non-zero exit is a business outcome
(e.g. the split output is missing). Pure parsers:
:func:`parseChunkRefs` (shared with tests) and
:func:`parseChunkHeaders`.
"""

from __future__ import annotations

import logging
import re
import shlex

from deepagents.backends.sandbox import BaseSandbox

from app.services.agent_v2.types import ChunkInventory, ChunkRef
from app.services.sandbox.types import SandboxCtx
from app.utils.branded import CommitId, PRNumber, RepoId
from app.workflows.review_v2.errors import (
    ChunkListError,
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

_CHUNK_HEADER_PREFIX = "### "

_CHUNK_REF_RE = re.compile(r"^(?P<chunk>.+):### (?P<path>.+)$")
"""One ``grep -H '^### '`` line: ``<chunk file>:### <real path>``.

``grep -H`` joins the file name and the matched header line with a
bare colon (no space). Greedy on the chunk side: chunk names may
themselves contain colons (the split script only flattens ``/``),
while real paths never contain ``:### `` in practice — so the split
lands on the last separator.
"""

_LIST_TIMEOUT_S = 60


def parseChunkRefs(grepOutput: str) -> list[ChunkRef]:
    """Parse ``grep -H '^### '`` output into sorted chunk refs.

    Each input line is ``<chunk file>:### <real path>`` (``-H`` prints
    the file name; the chunk header inside the file carries the real
    path). Matched by :data:`_CHUNK_REF_RE` (greedy chunk side — chunk
    names may contain colons, real paths effectively never contain
    ``":### "``). Blank lines and non-header lines are ignored.
    Duplicate real paths dedupe to the first chunk seen (deterministic:
    input order wins, output sorted by path).
    """
    seen: dict[str, str] = {}
    for line in grepOutput.splitlines():
        match = _CHUNK_REF_RE.match(line.strip())
        if match is None:
            continue
        chunk = match.group("chunk").strip().rsplit("/", 1)[-1]
        path = match.group("path").strip()
        if chunk and path and path not in seen:
            seen[path] = chunk
    return [
        ChunkRef(filePath=path, diffPath=seen[path]) for path in sorted(seen)
    ]


def parseChunkHeaders(grepOutput: str) -> list[str]:
    """Parse ``grep -h '^### '`` output into sorted real paths.

    One ``### <real path>`` header per chunk; blank lines and
    non-header lines are ignored. Dedupes while preserving
    determinism (sorted output). Kept for the header-only shape;
    prefer :func:`parseChunkRefs` when the chunk file names matter.
    """
    paths: set[str] = set()
    for line in grepOutput.splitlines():
        stripped = line.strip()
        if not stripped.startswith(_CHUNK_HEADER_PREFIX):
            continue
        path = stripped[len(_CHUNK_HEADER_PREFIX) :].strip()
        if path:
            paths.add(path)
    return sorted(paths)


async def listChunkFiles(
    sandbox: BaseSandbox,
    *,
    repoId: RepoId,
    prNumber: PRNumber,
    headSha: CommitId,
) -> ChunkInventory | ChunkListError:
    """Inventory ``splitted_diffs/``: chunk headers → real paths + diff files."""
    chunksDir = f"/home/user/tmp/{prNumber}/{headSha}/splitted_diffs"
    backend = asAsyncSandbox(sandbox)

    try:
        result = await backend.aexecute(
            f"grep -H {shlex.quote('^### ')} {shlex.quote(chunksDir)}/*.md",
            timeout=_LIST_TIMEOUT_S,
        )
    except Exception as exc:
        return ChunkListError(
            message=f"failed to list split chunks: {type(exc).__name__}: {exc}",
            repoId=repoId,
            prNumber=prNumber,
            headSha=headSha,
            retryable=True,
        )

    if result.exit_code in (-1, 124):
        return ChunkListError(
            message=f"runner dropped the chunk listing (exit {result.exit_code})",
            repoId=repoId,
            prNumber=prNumber,
            headSha=headSha,
            retryable=True,
        )
    if result.exit_code != 0:
        # grep exits 1 on no matches (empty diff edge) — but an empty
        # inventory is only valid when the split summary agrees; the
        # workflow decides that. Here: no headers parsed → empty list,
        # unless the command itself failed for another reason.
        tail = truncateOutput(result.output, maxChars=600)
        if result.exit_code == 1 and not tail:
            return ChunkInventory(actualFiles=[], chunks=[])
        return ChunkListError(
            message=f"chunk listing exited {result.exit_code}: {tail}",
            repoId=repoId,
            prNumber=prNumber,
            headSha=headSha,
            retryable=False,
        )

    refs = parseChunkRefs(result.output)
    return ChunkInventory(
        actualFiles=[ref.filePath for ref in refs],
        chunks=refs,
    )


async def listChunkFilesStep(
    *,
    sandboxCtx: SandboxCtx,
    repoId: RepoId,
    prNumber: PRNumber,
    headSha: CommitId,
) -> ChunkInventory:
    """Inventory the ``splitted_diffs/`` chunks.

    On success the returned :class:`ChunkInventory` carries the
    reviewable real paths (the fan-out truth) without any diff text.

    Raises:
        TransientReviewStepFailure: sandbox reconnect / listing
            failed transiently.
        ReviewStepFailure: the listing failed finally.
    """
    sandbox = await connectSandbox(sandboxCtx)
    if isinstance(sandbox, SandboxConnectError):
        raise TransientReviewStepFailure(sandbox)

    result = await listChunkFiles(
        sandbox,
        repoId=repoId,
        prNumber=prNumber,
        headSha=headSha,
    )
    if isinstance(result, ChunkListError):
        if result.retryable:
            raise TransientReviewStepFailure(result)
        raise ReviewStepFailure(result)

    log.info(
        "list_chunks_step: ok pr_number=%s files=%d",
        prNumber,
        len(result.actualFiles),
    )
    return result


__all__ = [
    "listChunkFiles",
    "listChunkFilesStep",
    "parseChunkHeaders",
    "parseChunkRefs",
]
