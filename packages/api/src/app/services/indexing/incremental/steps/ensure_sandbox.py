"""Step: create the ephemeral incremental-index sandbox.

Identical lifecycle to :func:`app.services.indexing.steps.ensureIndexSandbox`
— every run creates a **fresh** E2B sandbox from the dedicated
``INDEX_SANDBOX_TEMPLATE_NAME`` template (baked with ``lancedb`` +
``openai`` + ``tree-sitter-language-pack``), carries only the
``sandbox_id`` onward, and is killed by the workflow's ``finally``.
No sandbox is ever shared between runs.

Returns an :class:`IncrementalIndexContext` — an :class:`IndexContext`
plus the ``index_files`` list the append script consumes, so the shared
index steps (:func:`connect_index_sandbox`, :func:`gitCloneToSandbox`,
:func:`stopIndexerSandbox`) accept it unchanged.
"""

from __future__ import annotations

import logging

from dbos import DBOS

from app.core.config import settings
from app.core.sandbox.e2b import INDEX_SANDBOX_TEMPLATE_NAME, E2BSandbox
from app.core.sandbox.types import SandboxSpec
from app.services.indexing.errors import (
    IndexingConfigError,
    IndexingError,
    IndexSandboxCreateError,
    _should_retry_index,
)
from app.services.indexing.incremental.types import (
    IncrementalIndexContext,
    IncrementalIndexWorkflowInput,
)
from app.services.indexing.steps.ensure_index_sandbox import _resolve_table_uri
from app.utils.util import repo_path, scripts_path

log = logging.getLogger(__name__)


def _incremental_sandbox_spec() -> SandboxSpec:
    """Build the E2B spec pointing the sandbox at the indexing template."""
    if not settings.e2b_api_key:
        raise IndexingConfigError(
            detail="E2B_API_KEY is not set (required for the indexing sandbox)"
        )
    return SandboxSpec(
        provider="e2b",
        api_key=settings.e2b_api_key,
        template=INDEX_SANDBOX_TEMPLATE_NAME,
        cpu_count=settings.e2b_cpu_count,
        memory_mb=settings.e2b_memory_mb,
        timeout_s=settings.e2b_timeout_s,
    )


@DBOS.step(
    retries_allowed=True,
    max_attempts=3,
    should_retry=_should_retry_index,
)
async def ensureIncrementalSandbox(
    input: IncrementalIndexWorkflowInput,
) -> IncrementalIndexContext:
    """Create the sandbox and build the :class:`IncrementalIndexContext`.

    Order of operations is deliberate:

    1. Gate on :attr:`Settings.indexing_configured` — final
       :class:`IndexingConfigError`.
    2. Create the E2B sandbox on the indexing template — wrapped in
       :class:`IndexSandboxCreateError` (transient) so the retry
       policy re-runs the whole step (each retry gets its own fresh
       sandbox; a leaked sandbox from a failed attempt is killed by
       the workflow's ``finally`` only if the context survives — a
       create failure has no context yet, so the retry simply creates
       another one).

    Returns:
        :class:`IncrementalIndexContext` carrying every id and path
        the rest of the workflow needs. Frozen so DBOS can serialize it.
    """
    owner: str = input.repo_owner
    repo: str = input.repo_name

    if not settings.indexing_configured:
        raise IndexingConfigError()

    spec = _incremental_sandbox_spec()
    sandbox = E2BSandbox(
        spec=spec,
        user_id=input.user_id,
        repo_id=f"index:{owner}:{repo}",
        sandbox_name=f"incr-{owner}-{repo}",
    )
    try:
        await sandbox.create()
    except IndexingError:
        raise
    except Exception as exc:
        log.exception(
            "ensure_incremental_sandbox: e2b create failed: owner=%s repo=%s",
            owner,
            repo,
        )
        raise IndexSandboxCreateError(cause=f"{type(exc).__name__}: {exc}") from exc

    log.info(
        "ensure_incremental_sandbox: ok sandbox_id=%s owner=%s repo=%s",
        sandbox.id,
        owner,
        repo,
    )
    return IncrementalIndexContext(
        user_id=input.user_id,
        sandbox_id=sandbox.id,
        sandbox_name=sandbox.sandbox_name,
        repo_owner=owner,
        repo_name=repo,
        repo_url=input.repo_url,
        default_branch=input.default_branch,
        repo_dir=repo_path(repo),
        ingest_script_path=f"{scripts_path()}/incremental_ingestion.py",
        table_uri=_resolve_table_uri(owner=owner, repo=repo),
        files_to_index=input.files_to_index,
    )


__all__ = ["ensureIncrementalSandbox"]
