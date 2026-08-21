### packages/api/src/app/services/indexing/incremental/steps/ensure_sandbox.py

```diff

deleted file mode 100644
index b72408f..0000000
--- a/packages/api/src/app/services/indexing/incremental/steps/ensure_sandbox.py
+++ /dev/null
@@ -1,129 +0,0 @@
    2       -"""Step: create the ephemeral incremental-index sandbox.
    3       -
    4       -Identical lifecycle to :func:`app.services.indexing.steps.ensureIndexSandbox`
    5       -— every run creates a **fresh** E2B sandbox from the dedicated
    6       -``INDEX_SANDBOX_TEMPLATE_NAME`` template (baked with ``lancedb`` +
    7       -``openai`` + ``tree-sitter-language-pack``), carries only the
    8       -``sandbox_id`` onward, and is killed by the workflow's ``finally``.
    9       -No sandbox is ever shared between runs.
   10       -
   11       -Returns an :class:`IncrementalIndexContext` — an :class:`IndexContext`
   12       -plus the ``index_files`` list the append script consumes, so the shared
   13       -index steps (:func:`connect_index_sandbox`, :func:`gitCloneToSandbox`,
   14       -:func:`stopIndexerSandbox`) accept it unchanged.
   15       -"""
   16       -
   17       -from __future__ import annotations
   18       -
   19       -import logging
   20       -
   21       -from dbos import DBOS
   22       -
   23       -from app.core.config import settings
   24       -from app.core.sandbox.e2b import INDEX_SANDBOX_TEMPLATE_NAME, E2BSandbox
   25       -from app.core.sandbox.types import SandboxSpec
   26       -from app.services.indexing.errors import (
   27       -    IndexingConfigError,
   28       -    IndexingError,
   29       -    IndexSandboxCreateError,
   30       -    _should_retry_index,
   31       -)
   32       -from app.services.indexing.incremental.types import (
   33       -    IncrementalIndexContext,
   34       -    IncrementalIndexWorkflowInput,
   35       -)
   36       -from app.services.indexing.steps.ensure_index_sandbox import _resolve_table_uri
   37       -from app.utils.util import repo_path, scripts_path
   38       -
   39       -log = logging.getLogger(__name__)
   40       -
   41       -
   42       -def _incremental_sandbox_spec() -> SandboxSpec:
   43       -    """Build the E2B spec pointing the sandbox at the indexing template."""
   44       -    if not settings.e2b_api_key:
   45       -        raise IndexingConfigError(
   46       -            detail="E2B_API_KEY is not set (required for the indexing sandbox)"
   47       -        )
   48       -    return SandboxSpec(
   49       -        provider="e2b",
   50       -        api_key=settings.e2b_api_key,
   51       -        template=INDEX_SANDBOX_TEMPLATE_NAME,
   52       -        cpu_count=settings.e2b_cpu_count,
   53       -        memory_mb=settings.e2b_memory_mb,
   54       -        timeout_s=settings.e2b_timeout_s,
   55       -    )
   56       -
   57       -
   58       -@DBOS.step(
   59       -    retries_allowed=True,
   60       -    max_attempts=3,
   61       -    should_retry=_should_retry_index,
   62       -)
   63       -async def ensureIncrementalSandbox(
   64       -    input: IncrementalIndexWorkflowInput,
   65       -) -> IncrementalIndexContext:
   66       -    """Create the sandbox and build the :class:`IncrementalIndexContext`.
   67       -
   68       -    Order of operations is deliberate:
   69       -
   70       -    1. Gate on :attr:`Settings.indexing_configured` — final
   71       -       :class:`IndexingConfigError`.
   72       -    2. Create the E2B sandbox on the indexing template — wrapped in
   73       -       :class:`IndexSandboxCreateError` (transient) so the retry
   74       -       policy re-runs the whole step (each retry gets its own fresh
   75       -       sandbox; a leaked sandbox from a failed attempt is killed by
   76       -       the workflow's ``finally`` only if the context survives — a
   77       -       create failure has no context yet, so the retry simply creates
   78       -       another one).
   79       -
   80       -    Returns:
   81       -        :class:`IncrementalIndexContext` carrying every id and path
   82       -        the rest of the workflow needs. Frozen so DBOS can serialize it.
   83       -    """
   84       -    owner: str = input.repo_owner
   85       -    repo: str = input.repo_name
   86       -
   87       -    if not settings.indexing_configured:
   88       -        raise IndexingConfigError()
   89       -
   90       -    spec = _incremental_sandbox_spec()
   91       -    sandbox = E2BSandbox(
   92       -        spec=spec,
   93       -        user_id=input.user_id,
   94       -        repo_id=f"index:{owner}:{repo}",
   95       -        sandbox_name=f"incr-{owner}-{repo}",
   96       -    )
   97       -    try:
   98       -        await sandbox.create()
   99       -    except IndexingError:
  100       -        raise
  101       -    except Exception as exc:
  102       -        log.exception(
  103       -            "ensure_incremental_sandbox: e2b create failed: owner=%s repo=%s",
  104       -            owner,
  105       -            repo,
  106       -        )
  107       -        raise IndexSandboxCreateError(cause=f"{type(exc).__name__}: {exc}") from exc
  108       -
  109       -    log.info(
  110       -        "ensure_incremental_sandbox: ok sandbox_id=%s owner=%s repo=%s",
  111       -        sandbox.id,
  112       -        owner,
  113       -        repo,
  114       -    )
  115       -    return IncrementalIndexContext(
  116       -        user_id=input.user_id,
  117       -        sandbox_id=sandbox.id,
  118       -        sandbox_name=sandbox.sandbox_name,
  119       -        repo_owner=owner,
  120       -        repo_name=repo,
  121       -        repo_url=input.repo_url,
  122       -        default_branch=input.default_branch,
  123       -        repo_dir=repo_path(repo),
  124       -        ingest_script_path=f"{scripts_path()}/incremental_ingestion.py",
  125       -        table_uri=_resolve_table_uri(owner=owner, repo=repo),
  126       -        files_to_index=input.files_to_index,
  127       -    )
  128       -
  129       -
  130       -__all__ = ["ensureIncrementalSandbox"]

```
