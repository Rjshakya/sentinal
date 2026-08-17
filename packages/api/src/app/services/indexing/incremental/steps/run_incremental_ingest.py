"""Step: run the in-sandbox incremental append command end-to-end.

Mirrors :mod:`app.services.indexing.steps.run_index` for the
append-only path: one DBOS step runs
``python3 incremental_ingestion.py <repo_dir> --files <rel...>``
inside the (freshly created) indexing sandbox. The script owns
everything from tree-sitter chunking of the listed files through the
LanceDB append + FTS rebuild — chunks never cross the sandbox
boundary. The host only:

1. Connects to the sandbox.
2. Runs the script with the same env the full index uses
   (:func:`resolve_index_env`: AWS + OpenAI creds, table URI, batch
   size).
3. Maps the exit code to typed errors; parses the stdout summary line
   into the step's return value.

Exit-code mapping:

- ``0`` — success: parse the summary line.
- ``-1`` — sandbox runner dropout: transient, DBOS retries.
- ``> 0`` — script-level failure: final :class:`IncrementalIngestError`.
"""

from __future__ import annotations

import logging
import os
import shlex

from dbos import DBOS

from app.core.sandbox.e2b import E2BSandbox
from app.services.indexing.errors import _should_retry_index
from app.services.indexing.helpers import command_output_tail, parse_index_summary
from app.services.indexing.incremental.errors import (
    IncrementalIngestError,
    IncrementalIngestTransientError,
)
from app.services.indexing.incremental.types import IncrementalIndexContext
from app.services.indexing.steps._internal import connect_index_sandbox
from app.services.indexing.steps.run_index import (
    INDEX_RUN_TIMEOUT_S,
    resolve_index_env,
)

log = logging.getLogger(__name__)


def build_incremental_ingest_command(
    *,
    ingest_script_path: str,
    repo_dir: str,
    files: list[str],
) -> str:
    """Build the shell command the sandbox executes (pure, testable)."""
    parts = [
        "python3",
        ingest_script_path,
        repo_dir,
        "--files",
        *files,
    ]
    return " ".join(shlex.quote(part) for part in parts)


def check_incremental_ingest_result(result) -> None:
    """Map an in-sandbox run :class:`CommandResult` to typed errors.

    ``-1`` is a sandbox runner dropout (:class:`IncrementalIngestTransientError`);
    any other non-zero is a real in-sandbox failure
    (:class:`IncrementalIngestError`, final).
    """
    if result.exit_code == 0:
        return
    tail = command_output_tail(result)
    if result.exit_code == -1:
        raise IncrementalIngestTransientError(
            cause=tail or "sandbox command runner failure"
        )
    raise IncrementalIngestError(exit_code=result.exit_code, output_tail=tail)


@DBOS.step(
    retries_allowed=True,
    max_attempts=3,
    should_retry=_should_retry_index,
)
async def runIncrementalIngest(*, ctx: IncrementalIndexContext) -> tuple[int, int]:
    """Run the append-only chunking + ingestion command in the sandbox.

    Returns ``(chunk_count, file_count)`` as reported by the
    in-sandbox summary line; ``(0, 0)`` when ``ctx.index_files`` is
    empty (nothing to append — the webhook adapter normally gates this,
    but the workflow's pure-deletion path can reach here).

    Raises:
        IncrementalIngestTransientError: sandbox runner dropout. DBOS retries.
        IncrementalIngestError: the in-sandbox script exited non-zero. Final.
    """
    if not ctx.files_to_index:
        return 0, 0

    sandbox: E2BSandbox = await connect_index_sandbox(ctx)

    command = build_incremental_ingest_command(
        ingest_script_path=ctx.ingest_script_path,
        repo_dir=ctx.repo_dir,
        files=ctx.files_to_index,
    )

    env = resolve_index_env(
        table_uri=ctx.table_uri,
        batch_size=ctx.batch_size,
    )

    try:
        result = await sandbox.execute(
            command,
            cwd=os.path.dirname(ctx.ingest_script_path),
            envs=env,
            timeout=INDEX_RUN_TIMEOUT_S,
        )
    except Exception as exc:
        log.warning(
            "run_incremental_ingest: execute failed owner=%s repo=%s cause=%s: %s",
            ctx.repo_owner,
            ctx.repo_name,
            type(exc).__name__,
            exc,
        )
        raise IncrementalIngestTransientError(
            cause=f"{type(exc).__name__}: {exc}"
        ) from exc

    check_incremental_ingest_result(result)

    # The script writes its summary to stdout. The last non-empty line
    # is the one we care about.
    summary_line = ""
    for raw_line in reversed((result.stdout or "").splitlines()):
        line = raw_line.strip()
        if line:
            summary_line = line
            break
    parsed = parse_index_summary(summary_line)
    if parsed is None:
        log.warning(
            "run_incremental_ingest: missing summary line owner=%s repo=%s stdout=%r",
            ctx.repo_owner,
            ctx.repo_name,
            result.stdout,
        )
        raise IncrementalIngestError(
            exit_code=0,
            output_tail=(
                "missing parseable summary line; "
                f"stdout={result.stdout!r} stderr={result.stderr!r}"
            ),
        )

    chunk_count, file_count = parsed
    log.info(
        "run_incremental_ingest: ok owner=%s repo=%s chunks=%d files=%d",
        ctx.repo_owner,
        ctx.repo_name,
        chunk_count,
        file_count,
    )
    return chunk_count, file_count


__all__ = [
    "build_incremental_ingest_command",
    "check_incremental_ingest_result",
    "runIncrementalIngest",
]
