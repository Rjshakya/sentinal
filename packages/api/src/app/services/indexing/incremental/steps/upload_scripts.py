"""Step: write the in-sandbox incremental scripts into the sandbox.

The incremental append script lives in this package's ``scripts/``
directory (``incremental/scripts/incremental_ingestion.py``) — not in
the shared ``indexing/scripts/`` folder, so the two pipelines stay
independent. It imports ``chunking`` as a sibling module, so this step
also uploads the **shared** ``indexing/scripts/chunking.py``; both land
in the same ``<sandbox>/sentinel-workspace/context/`` directory.

LanceDB / OpenAI / tree-sitter-language-pack are baked into the
indexing template, so no pip install runs here. Filesystem writes are
transient by nature; DBOS retries the step, which re-writes both files
(idempotent).
"""

from __future__ import annotations

import logging
from pathlib import Path

from dbos import DBOS

from app.core.sandbox.e2b import E2BSandbox
from app.services.indexing.errors import ScriptSetupError, _should_retry_index
from app.services.indexing.incremental.types import IncrementalIndexContext
from app.services.indexing.steps._internal import connect_index_sandbox
from app.utils.util import scripts_path

log = logging.getLogger(__name__)

_INCREMENTAL_SCRIPTS_DIR: Path = Path(__file__).resolve().parent.parent / "scripts"
"""Directory holding this pipeline's in-sandbox files (host reads them as bytes)."""

_SHARED_SCRIPTS_DIR: Path = Path(__file__).resolve().parent.parent.parent / "scripts"
"""Shared ``indexing/scripts/`` — the source of the tree-sitter chunking module."""


def build_incremental_scripts_args(
    *,
    ingest_script_path: str,
) -> tuple[str, str]:
    """Resolve the per-run (remote path, source path) tuples.

    Pure / testable. Both files land under :func:`scripts_path`
    (``<sandbox>/sentinel-workspace/context/``) so
    ``incremental_ingestion.py``'s ``sys.path.insert`` sibling import
    of ``chunking`` works.
    """
    chunking_path = f"{scripts_path()}/chunking.py"
    return chunking_path, ingest_script_path


@DBOS.step(
    retries_allowed=True,
    max_attempts=3,
    should_retry=_should_retry_index,
)
async def uploadIncrementalScripts(*, ctx: IncrementalIndexContext) -> None:
    """Write ``chunking.py`` + ``incremental_ingestion.py`` into the sandbox.

    Each file is read once from disk on the host and shipped over
    ``fs_write``. Idempotent: ``fs_write`` overwrites on every call.

    Raises:
        ScriptSetupError: fs write failed. Transient — DBOS retries.
    """
    sandbox: E2BSandbox = await connect_index_sandbox(ctx)
    chunking_path, ingest_path = build_incremental_scripts_args(
        ingest_script_path=ctx.ingest_script_path,
    )

    chunking_src = _SHARED_SCRIPTS_DIR / "chunking.py"
    ingestion_src = _INCREMENTAL_SCRIPTS_DIR / "incremental_ingestion.py"

    try:
        await sandbox.fs_create_folder(scripts_path())
        await sandbox.fs_write(
            chunking_path, chunking_src.read_text(encoding="utf-8")
        )
        await sandbox.fs_write(
            ingest_path, ingestion_src.read_text(encoding="utf-8")
        )
    except ScriptSetupError:
        raise
    except Exception as exc:
        log.warning(
            "upload_incremental_scripts: fs failure owner=%s repo=%s cause=%s: %s",
            ctx.repo_owner,
            ctx.repo_name,
            type(exc).__name__,
            exc,
        )
        raise ScriptSetupError(
            cause=f"{type(exc).__name__}: {exc}"
        ) from exc

    log.info(
        "upload_incremental_scripts: ok owner=%s repo=%s scripts=%s",
        ctx.repo_owner,
        ctx.repo_name,
        scripts_path(),
    )


__all__ = ["build_incremental_scripts_args", "uploadIncrementalScripts"]
