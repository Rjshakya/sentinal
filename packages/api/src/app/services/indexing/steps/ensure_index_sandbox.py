"""Step 1: create the ephemeral index sandbox and derive the run context.

Creates a fresh E2B sandbox from the dedicated
``INDEX_SANDBOX_TEMPLATE_NAME`` template (which bakes in
``lancedb`` + ``openai`` + ``tree-sitter-language-pack``). Parses
``owner/repo`` from the URL and returns the :class:`IndexContext`
every later step reconnects through.

The dataset URI is computed up front so a config error fails fast
here instead of after the clone. The host never opens LanceDB — the
URI is passed to the in-sandbox ingestion script via ``envs=`` only.
"""

from __future__ import annotations

import logging

from dbos import DBOS

from app.core.config import settings
from app.core.sandbox.e2b import INDEX_SANDBOX_TEMPLATE_NAME
from app.core.sandbox.types import SandboxSpec
from app.services.indexing.errors import (
    IndexingConfigError,
    IndexingError,
    IndexSandboxCreateError,
    _should_retry_index,
)
from app.services.indexing.helpers import (
    build_table_uri,
    parse_repo_url,
)
from app.services.indexing.types import IndexContext, IndexWorkflowInput
from app.utils.util import repo_path, scripts_path

log = logging.getLogger(__name__)


def _index_sandbox_spec() -> SandboxSpec:
    """Build the E2B spec pointing the sandbox at the indexing template.

    Reuses the API key from the active provider's settings; only the
    template name differs from a generic E2B sandbox.
    """
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


def _resolve_table_uri(*, owner: str, repo: str) -> str:
    """S3 URI for the repo's LanceDB dataset (one dataset per repo)."""
    if not settings.index_s3_bucket:
        raise IndexingConfigError(
            detail="INDEX_S3_BUCKET is not set (required for the indexing pipeline)"
        )
    return build_table_uri(
        bucket=settings.index_s3_bucket,
        prefix=settings.index_s3_prefix,
        owner=owner,
        repo=repo,
    )


@DBOS.step(
    retries_allowed=True,
    max_attempts=3,
    should_retry=_should_retry_index,
)
async def ensureIndexSandbox(
    input: IndexWorkflowInput,
) -> IndexContext:
    """Create the sandbox and build the :class:`IndexContext`.

    Order of operations is deliberate:

    1. Parse ``owner/repo`` from the URL — final :class:`InvalidRepoUrlError`.
    2. Gate on :attr:`Settings.indexing_configured` — final
       :class:`IndexingConfigError`.
    3. Create the E2B sandbox on the indexing template — wrapped in
       :class:`IndexSandboxCreateError` (transient) so the retry
       policy re-runs the whole step.

    Returns:
        :class:`IndexContext` carrying every id and path the rest of
        the workflow needs. Frozen so DBOS can serialize it.
    """
    owner, repo = parse_repo_url(input.repo_url)

    if not settings.indexing_configured:
        raise IndexingConfigError()

    from app.core.sandbox.e2b import E2BSandbox

    spec = _index_sandbox_spec()
    sandbox = E2BSandbox(
        spec=spec,
        user_id=input.user_id,
        repo_id=f"index:{owner}:{repo}",
        sandbox_name=f"index-{owner}-{repo}",
    )
    try:
        await sandbox.create()
    except IndexingError:
        raise
    except Exception as exc:
        log.exception(
            "ensure_index_sandbox: e2b create failed: owner=%s repo=%s",
            owner,
            repo,
        )
        raise IndexSandboxCreateError(
            cause=f"{type(exc).__name__}: {exc}"
        ) from exc

    log.info(
        "ensure_index_sandbox: ok sandbox_id=%s owner=%s repo=%s",
        sandbox.id,
        owner,
        repo,
    )
    return IndexContext(
        user_id=input.user_id,
        sandbox_id=sandbox.id,
        sandbox_name=sandbox.sandbox_name,
        repo_owner=owner,
        repo_name=repo,
        repo_url=input.repo_url,
        default_branch=input.default_branch,
        repo_dir=repo_path(repo),
        ingest_script_path=f"{scripts_path()}/ingestion.py",
        table_uri=_resolve_table_uri(owner=owner, repo=repo),
    )


__all__ = ["_resolve_table_uri", "ensureIndexSandbox"]
