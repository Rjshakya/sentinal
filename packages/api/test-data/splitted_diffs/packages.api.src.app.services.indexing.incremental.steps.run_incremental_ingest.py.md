### packages/api/src/app/services/indexing/incremental/steps/run_incremental_ingest.py

```diff

deleted file mode 100644
index b958502..0000000
--- a/packages/api/src/app/services/indexing/incremental/steps/run_incremental_ingest.py
+++ /dev/null
@@ -1,177 +0,0 @@
    2       -"""Step: run the in-sandbox incremental append command end-to-end.
    3       -
    4       -Mirrors :mod:`app.services.indexing.steps.run_index` for the
    5       -append-only path: one DBOS step runs
    6       -``python3 incremental_ingestion.py <repo_dir> --files <rel...>``
    7       -inside the (freshly created) indexing sandbox. The script owns
    8       -everything from tree-sitter chunking of the listed files through the
    9       -LanceDB append + FTS rebuild — chunks never cross the sandbox
   10       -boundary. The host only:
   11       -
   12       -1. Connects to the sandbox.
   13       -2. Runs the script with the same env the full index uses
   14       -   (:func:`resolve_index_env`: AWS + OpenAI creds, table URI, batch
   15       -   size).
   16       -3. Maps the exit code to typed errors; parses the stdout summary line
   17       -   into the step's return value.
   18       -
   19       -Exit-code mapping:
   20       -
   21       -- ``0`` — success: parse the summary line.
   22       -- ``-1`` — sandbox runner dropout: transient, DBOS retries.
   23       -- ``> 0`` — script-level failure: final :class:`IncrementalIngestError`.
   24       -"""
   25       -
   26       -from __future__ import annotations
   27       -
   28       -import logging
   29       -import os
   30       -import shlex
   31       -
   32       -from dbos import DBOS
   33       -
   34       -from app.core.sandbox.e2b import E2BSandbox
   35       -from app.services.indexing.errors import _should_retry_index
   36       -from app.services.indexing.helpers import command_output_tail, parse_index_summary
   37       -from app.services.indexing.incremental.errors import (
   38       -    IncrementalIngestError,
   39       -    IncrementalIngestTransientError,
   40       -)
   41       -from app.services.indexing.incremental.types import IncrementalIndexContext
   42       -from app.services.indexing.steps._internal import connect_index_sandbox
   43       -from app.services.indexing.steps.run_index import (
   44       -    INDEX_RUN_TIMEOUT_S,
   45       -    resolve_index_env,
   46       -)
   47       -
   48       -log = logging.getLogger(__name__)
   49       -
   50       -
   51       -def build_incremental_ingest_command(
   52       -    *,
   53       -    ingest_script_path: str,
   54       -    repo_dir: str,
   55       -    files: list[str],
   56       -) -> str:
   57       -    """Build the shell command the sandbox executes (pure, testable)."""
   58       -    parts = [
   59       -        "python3",
   60       -        ingest_script_path,
   61       -        repo_dir,
   62       -        "--files",
   63       -        *files,
   64       -    ]
   65       -    return " ".join(shlex.quote(part) for part in parts)
   66       -
   67       -
   68       -def check_incremental_ingest_result(result) -> None:
   69       -    """Map an in-sandbox run :class:`CommandResult` to typed errors.
   70       -
   71       -    ``-1`` is a sandbox runner dropout (:class:`IncrementalIngestTransientError`);
   72       -    any other non-zero is a real in-sandbox failure
   73       -    (:class:`IncrementalIngestError`, final).
   74       -    """
   75       -    if result.exit_code == 0:
   76       -        return
   77       -    tail = command_output_tail(result)
   78       -    if result.exit_code == -1:
   79       -        raise IncrementalIngestTransientError(
   80       -            cause=tail or "sandbox command runner failure"
   81       -        )
   82       -    raise IncrementalIngestError(exit_code=result.exit_code, output_tail=tail)
   83       -
   84       -
   85       -@DBOS.step(
   86       -    retries_allowed=True,
   87       -    max_attempts=3,
   88       -    should_retry=_should_retry_index,
   89       -)
   90       -async def runIncrementalIngest(*, ctx: IncrementalIndexContext) -> tuple[int, int]:
   91       -    """Run the append-only chunking + ingestion command in the sandbox.
   92       -
   93       -    Returns ``(chunk_count, file_count)`` as reported by the
   94       -    in-sandbox summary line; ``(0, 0)`` when ``ctx.index_files`` is
   95       -    empty (nothing to append — the webhook adapter normally gates this,
   96       -    but the workflow's pure-deletion path can reach here).
   97       -
   98       -    Raises:
   99       -        IncrementalIngestTransientError: sandbox runner dropout. DBOS retries.
  100       -        IncrementalIngestError: the in-sandbox script exited non-zero. Final.
  101       -    """
  102       -    if not ctx.files_to_index:
  103       -        return 0, 0
  104       -
  105       -    sandbox: E2BSandbox = await connect_index_sandbox(ctx)
  106       -
  107       -    command = build_incremental_ingest_command(
  108       -        ingest_script_path=ctx.ingest_script_path,
  109       -        repo_dir=ctx.repo_dir,
  110       -        files=ctx.files_to_index,
  111       -    )
  112       -
  113       -    env = resolve_index_env(
  114       -        table_uri=ctx.table_uri,
  115       -        batch_size=ctx.batch_size,
  116       -    )
  117       -
  118       -    try:
  119       -        result = await sandbox.execute(
  120       -            command,
  121       -            cwd=os.path.dirname(ctx.ingest_script_path),
  122       -            envs=env,
  123       -            timeout=INDEX_RUN_TIMEOUT_S,
  124       -        )
  125       -    except Exception as exc:
  126       -        log.warning(
  127       -            "run_incremental_ingest: execute failed owner=%s repo=%s cause=%s: %s",
  128       -            ctx.repo_owner,
  129       -            ctx.repo_name,
  130       -            type(exc).__name__,
  131       -            exc,
  132       -        )
  133       -        raise IncrementalIngestTransientError(
  134       -            cause=f"{type(exc).__name__}: {exc}"
  135       -        ) from exc
  136       -
  137       -    check_incremental_ingest_result(result)
  138       -
  139       -    # The script writes its summary to stdout. The last non-empty line
  140       -    # is the one we care about.
  141       -    summary_line = ""
  142       -    for raw_line in reversed((result.stdout or "").splitlines()):
  143       -        line = raw_line.strip()
  144       -        if line:
  145       -            summary_line = line
  146       -            break
  147       -    parsed = parse_index_summary(summary_line)
  148       -    if parsed is None:
  149       -        log.warning(
  150       -            "run_incremental_ingest: missing summary line owner=%s repo=%s stdout=%r",
  151       -            ctx.repo_owner,
  152       -            ctx.repo_name,
  153       -            result.stdout,
  154       -        )
  155       -        raise IncrementalIngestError(
  156       -            exit_code=0,
  157       -            output_tail=(
  158       -                "missing parseable summary line; "
  159       -                f"stdout={result.stdout!r} stderr={result.stderr!r}"
  160       -            ),
  161       -        )
  162       -
  163       -    chunk_count, file_count = parsed
  164       -    log.info(
  165       -        "run_incremental_ingest: ok owner=%s repo=%s chunks=%d files=%d",
  166       -        ctx.repo_owner,
  167       -        ctx.repo_name,
  168       -        chunk_count,
  169       -        file_count,
  170       -    )
  171       -    return chunk_count, file_count
  172       -
  173       -
  174       -__all__ = [
  175       -    "build_incremental_ingest_command",
  176       -    "check_incremental_ingest_result",
  177       -    "runIncrementalIngest",
  178       -]

```
