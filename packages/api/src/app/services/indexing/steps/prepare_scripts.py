"""Step: write the in-sandbox scripts into the sandbox.

Uploads ``chunking.py`` and ``ingestion.py`` (read from disk on the
host) into ``<workspace>/context/`` inside the indexing sandbox.
LanceDB / OpenAI / tree-sitter-language-pack are baked into the
indexing template by
:func:`app.core.sandbox.e2b.build_e2b_index_template`, so no pip
install runs here.

Filesystem writes are transient by nature (network blips); DBOS
retries the step, which re-writes both files. Idempotent.
"""

from __future__ import annotations

import logging
from pathlib import Path

from dbos import DBOS

from app.core.sandbox.e2b import E2BSandbox
from app.services.indexing.errors import (
    ScriptSetupError,
    _should_retry_index,
)
from app.services.indexing.steps._internal import connect_index_sandbox
from app.services.indexing.types import IndexContext
from app.utils.util import scripts_path

log = logging.getLogger(__name__)

_SCRIPTS_DIR: Path = Path(__file__).resolve().parent.parent / "scripts"
"""Directory holding the in-sandbox files; the host reads them as bytes."""


def build_prepare_scripts_args(*, ingest_script_path: str) -> tuple[str, str]:
    """Resolve the per-run (remote path, source path) tuples.

    Pure / testable. The in-sandbox resolver convention places both
    files under :func:`scripts_path` (``<sandbox>/sentinel-workspace/
    context/``), regardless of the exact ``ingest_script_path``
    subpath, because ``ingestion.py`` imports ``chunking`` as a
    sibling module via :func:`sys.path.insert`.
    """
    chunking_path = f"{scripts_path()}/chunking.py"
    return chunking_path, ingest_script_path


@DBOS.step(
    retries_allowed=True,
    max_attempts=3,
    should_retry=_should_retry_index,
)
async def uploadScriptsToSandbox(*, ctx: IndexContext) -> None:
    """Write ``chunking.py`` + ``ingestion.py`` into the sandbox.

    Each file is read once from :data:`_SCRIPTS_DIR` on the host and
    shipped over ``fs_write``. Idempotent: ``fs_write`` overwrites on
    every call.

    Raises:
        ScriptSetupError: fs write failed. Transient — DBOS retries.
    """
    sandbox: E2BSandbox = await connect_index_sandbox(ctx)
    chunking_path, ingest_path = build_prepare_scripts_args(
        ingest_script_path=ctx.ingest_script_path,
    )

    chunking_src = _SCRIPTS_DIR / "chunking.py"
    ingestion_src = _SCRIPTS_DIR / "ingestion.py"

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
            "prepare_scripts: fs failure owner=%s repo=%s cause=%s: %s",
            ctx.repo_owner,
            ctx.repo_name,
            type(exc).__name__,
            exc,
        )
        raise ScriptSetupError(
            cause=f"{type(exc).__name__}: {exc}"
        ) from exc

    log.info(
        "prepare_scripts: ok owner=%s repo=%s scripts=%s",
        ctx.repo_owner,
        ctx.repo_name,
        scripts_path(),
    )


__all__ = ["build_prepare_scripts_args", "uploadScriptsToSandbox"]
