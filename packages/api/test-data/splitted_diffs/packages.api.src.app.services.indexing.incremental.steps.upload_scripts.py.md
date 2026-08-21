### packages/api/src/app/services/indexing/incremental/steps/upload_scripts.py

```diff

deleted file mode 100644
index 1da926b..0000000
--- a/packages/api/src/app/services/indexing/incremental/steps/upload_scripts.py
+++ /dev/null
@@ -1,105 +0,0 @@
    2       -"""Step: write the in-sandbox incremental scripts into the sandbox.
    3       -
    4       -The incremental append script lives in this package's ``scripts/``
    5       -directory (``incremental/scripts/incremental_ingestion.py``) — not in
    6       -the shared ``indexing/scripts/`` folder, so the two pipelines stay
    7       -independent. It imports ``chunking`` as a sibling module, so this step
    8       -also uploads the **shared** ``indexing/scripts/chunking.py``; both land
    9       -in the same ``<sandbox>/sentinel-workspace/context/`` directory.
   10       -
   11       -LanceDB / OpenAI / tree-sitter-language-pack are baked into the
   12       -indexing template, so no pip install runs here. Filesystem writes are
   13       -transient by nature; DBOS retries the step, which re-writes both files
   14       -(idempotent).
   15       -"""
   16       -
   17       -from __future__ import annotations
   18       -
   19       -import logging
   20       -from pathlib import Path
   21       -
   22       -from dbos import DBOS
   23       -
   24       -from app.core.sandbox.e2b import E2BSandbox
   25       -from app.services.indexing.errors import ScriptSetupError, _should_retry_index
   26       -from app.services.indexing.incremental.types import IncrementalIndexContext
   27       -from app.services.indexing.steps._internal import connect_index_sandbox
   28       -from app.utils.util import scripts_path
   29       -
   30       -log = logging.getLogger(__name__)
   31       -
   32       -_INCREMENTAL_SCRIPTS_DIR: Path = Path(__file__).resolve().parent.parent / "scripts"
   33       -"""Directory holding this pipeline's in-sandbox files (host reads them as bytes)."""
   34       -
   35       -_SHARED_SCRIPTS_DIR: Path = Path(__file__).resolve().parent.parent.parent / "scripts"
   36       -"""Shared ``indexing/scripts/`` — the source of the tree-sitter chunking module."""
   37       -
   38       -
   39       -def build_incremental_scripts_args(
   40       -    *,
   41       -    ingest_script_path: str,
   42       -) -> tuple[str, str]:
   43       -    """Resolve the per-run (remote path, source path) tuples.
   44       -
   45       -    Pure / testable. Both files land under :func:`scripts_path`
   46       -    (``<sandbox>/sentinel-workspace/context/``) so
   47       -    ``incremental_ingestion.py``'s ``sys.path.insert`` sibling import
   48       -    of ``chunking`` works.
   49       -    """
   50       -    chunking_path = f"{scripts_path()}/chunking.py"
   51       -    return chunking_path, ingest_script_path
   52       -
   53       -
   54       -@DBOS.step(
   55       -    retries_allowed=True,
   56       -    max_attempts=3,
   57       -    should_retry=_should_retry_index,
   58       -)
   59       -async def uploadIncrementalScripts(*, ctx: IncrementalIndexContext) -> None:
   60       -    """Write ``chunking.py`` + ``incremental_ingestion.py`` into the sandbox.
   61       -
   62       -    Each file is read once from disk on the host and shipped over
   63       -    ``fs_write``. Idempotent: ``fs_write`` overwrites on every call.
   64       -
   65       -    Raises:
   66       -        ScriptSetupError: fs write failed. Transient — DBOS retries.
   67       -    """
   68       -    sandbox: E2BSandbox = await connect_index_sandbox(ctx)
   69       -    chunking_path, ingest_path = build_incremental_scripts_args(
   70       -        ingest_script_path=ctx.ingest_script_path,
   71       -    )
   72       -
   73       -    chunking_src = _SHARED_SCRIPTS_DIR / "chunking.py"
   74       -    ingestion_src = _INCREMENTAL_SCRIPTS_DIR / "incremental_ingestion.py"
   75       -
   76       -    try:
   77       -        await sandbox.fs_create_folder(scripts_path())
   78       -        await sandbox.fs_write(
   79       -            chunking_path, chunking_src.read_text(encoding="utf-8")
   80       -        )
   81       -        await sandbox.fs_write(
   82       -            ingest_path, ingestion_src.read_text(encoding="utf-8")
   83       -        )
   84       -    except ScriptSetupError:
   85       -        raise
   86       -    except Exception as exc:
   87       -        log.warning(
   88       -            "upload_incremental_scripts: fs failure owner=%s repo=%s cause=%s: %s",
   89       -            ctx.repo_owner,
   90       -            ctx.repo_name,
   91       -            type(exc).__name__,
   92       -            exc,
   93       -        )
   94       -        raise ScriptSetupError(
   95       -            cause=f"{type(exc).__name__}: {exc}"
   96       -        ) from exc
   97       -
   98       -    log.info(
   99       -        "upload_incremental_scripts: ok owner=%s repo=%s scripts=%s",
  100       -        ctx.repo_owner,
  101       -        ctx.repo_name,
  102       -        scripts_path(),
  103       -    )
  104       -
  105       -
  106       -__all__ = ["build_incremental_scripts_args", "uploadIncrementalScripts"]

```
