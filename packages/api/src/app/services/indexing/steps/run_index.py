"""Step 4 (combined): run the in-sandbox indexing command end-to-end.

The single DBOS step runs ``python3 ingestion.py <repo_dir>`` inside
the indexing sandbox. The script owns everything from tree-sitter
chunking through the LanceDB writes — chunks never cross the sandbox
boundary. The host only has to:

1. Connect to the sandbox.
2. Run the ingestion entry point with the right env (``envs=`` carries
   AWS + OpenAI creds, the table URI, and the batch size).
3. Map the exit code to typed errors; parse the stdout summary line
   into the step's return value.

Exit-code mapping:

- ``0`` — success: parse the summary line.
- ``-1`` — sandbox runner dropout: transient, DBOS retries.
- ``> 0`` — script-level failure: final
  :class:`IndexRunError`.

Failure to parse the summary line on a successful exit is final: the
work completed (chunks were written) but the host cannot read the
row counts.
"""

from __future__ import annotations

import logging
import os
import shlex

from dbos import DBOS

from app.core.config import settings
from app.core.sandbox.e2b import E2BSandbox
from app.services.indexing.errors import (
    IndexRunError,
    IndexRunTransientError,
    _should_retry_index,
)
from app.services.indexing.helpers import command_output_tail, parse_index_summary
from app.services.indexing.steps._internal import connect_index_sandbox
from app.services.indexing.types import IndexContext

log = logging.getLogger(__name__)

INDEX_RUN_TIMEOUT_S: float = 1800.0
"""Upper bound on the in-sandbox indexing command's wall-clock runtime."""


def build_index_run_command(
    *,
    ingest_script_path: str,
    repo_dir: str,
) -> str:
    """Build the shell command the sandbox executes (pure, testable)."""
    parts = [
        "python3",
        ingest_script_path,
        repo_dir,
    ]
    return " ".join(shlex.quote(part) for part in parts)


def check_index_run_result(result) -> None:
    """Map an in-sandbox run :class:`CommandResult` to typed errors.

    ``-1`` is treated as a sandbox runner dropout
    (:class:`IndexRunTransientError`); any other non-zero is a real
    in-sandbox failure (:class:`IndexRunError`, final).
    """
    if result.exit_code == 0:
        return
    tail = command_output_tail(result)
    if result.exit_code == -1:
        raise IndexRunTransientError(cause=tail or "sandbox command runner failure")
    raise IndexRunError(exit_code=result.exit_code, output_tail=tail)


def resolve_index_env(*, table_uri: str, batch_size: int) -> dict[str, str]:
    """Build the env passed to the in-sandbox indexing command.

    Every secret-bearing value is read from the host's env (or
    settings) and forwarded only into the in-sandbox process â€" they
    never sit in the API process env or travel back to the client.

    All host env vars consumed here are required: a missing one
    raises :class:`IndexingConfigError` so the workflow fails fast
    with a typed error rather than wasting a sandbox on a doomed run.
    ``AWS_SESSION_TOKEN`` stays optional (forwarded only when set).
    """

    env: dict[str, str] = {
        "LANCEDB_TABLE_URI": table_uri,
        "LANCEDB_BATCH_SIZE": str(batch_size),
        "OPENAI_API_KEY": settings.openai_api_key,
        "AWS_ACCESS_KEY_ID": settings.aws_access_key_id,
        "AWS_SECRET_ACCESS_KEY": settings.aws_secret_access_key,
        "AWS_REGION": settings.aws_region,
        "AWS_ENDPOINT_URL": settings.aws_endpoint_url,
    }

    return env


@DBOS.step(
    retries_allowed=True,
    max_attempts=3,
    should_retry=_should_retry_index,
)
async def runIndexPipeline(*, ctx: IndexContext) -> tuple[int, int]:
    """Run the combined chunking + ingestion command in the sandbox.

    Returns ``(chunk_count, file_count)`` as reported by the
    in-sandbox summary line.

    Raises:
        IndexRunTransientError: sandbox runner dropout. DBOS retries.
        IndexRunError: the in-sandbox script exited non-zero. Final.
    """
    sandbox: E2BSandbox = await connect_index_sandbox(ctx)

    command = build_index_run_command(
        ingest_script_path=ctx.ingest_script_path,
        repo_dir=ctx.repo_dir,
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
            "run_index: execute failed owner=%s repo=%s cause=%s: %s",
            ctx.repo_owner,
            ctx.repo_name,
            type(exc).__name__,
            exc,
        )
        raise IndexRunTransientError(cause=f"{type(exc).__name__}: {exc}") from exc

    check_index_run_result(result)

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
            "run_index: missing summary line owner=%s repo=%s stdout=%r",
            ctx.repo_owner,
            ctx.repo_name,
            result.stdout,
        )
        raise IndexRunError(
            exit_code=0,
            output_tail=(
                "missing parseable summary line; "
                f"stdout={result.stdout!r} stderr={result.stderr!r}"
            ),
        )

    chunk_count, file_count = parsed
    log.info(
        "run_index: ok owner=%s repo=%s chunks=%d files=%d",
        ctx.repo_owner,
        ctx.repo_name,
        chunk_count,
        file_count,
    )
    return chunk_count, file_count


__all__ = [
    "INDEX_RUN_TIMEOUT_S",
    "build_index_run_command",
    "check_index_run_result",
    "resolve_index_env",
    "runIndexPipeline",
]
