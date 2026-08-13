"""Step modules for the indexing pipeline.

The pipeline has four steps:

1. :func:`ensureIndexSandbox` -- create the E2B sandbox.
2. :func:`gitCloneToSandbox` -- shallow-clone the repo.
3. :func:`uploadScriptsToSandbox` -- upload ``chunking.py`` +
   ``ingestion.py``.
4. :func:`runIndexPipeline` -- combined chunking + ingestion in one
   in-sandbox command.

Plus a best-effort teardown at the end of the workflow:
:func:`stopIndexerSandbox`.

Lifecycle-mirror steps (best-effort, never fail the workflow):

- :func:`create_index_run_step`
- :func:`mark_index_run_running_step`
- :func:`mark_index_run_success_step`
- :func:`mark_index_run_error_step`

Repo mirror steps (best-effort, flip :attr:`Repo.is_indexed` on the
parent row so the repo list endpoint + dashboard don't have to scan
``index_runs``):

- :func:`mark_repo_indexed_success_step`
- :func:`mark_repo_indexed_error_step`

DBOS keys step registration on ``__name__``. The camelCase names
above do not collide with the setup pipeline's snake_case
``git_clone_step`` / ``prepare_scripts_step``.
"""

from __future__ import annotations

from app.services.indexing.steps.ensure_index_sandbox import (
    _resolve_table_uri,
    ensureIndexSandbox,
)
from app.services.indexing.steps.git_clone import (
    build_clone_command,
    check_git_clone,
    gitCloneToSandbox,
)
from app.services.indexing.steps.index_run_steps import (
    create_index_run_step,
    mark_index_run_error_step,
    mark_index_run_running_step,
    mark_index_run_success_step,
)
from app.services.indexing.steps.prepare_scripts import (
    build_prepare_scripts_args,
    uploadScriptsToSandbox,
)
from app.services.indexing.steps.run_index import (
    INDEX_RUN_TIMEOUT_S,
    build_index_run_command,
    check_index_run_result,
    resolve_index_env,
    runIndexPipeline,
)
from app.services.indexing.steps.stop_sandbox import stopIndexerSandbox
from app.services.indexing.steps.update_repo import (
    mark_repo_indexed_error_step,
    mark_repo_indexed_success_step,
)

__all__ = [
    "INDEX_RUN_TIMEOUT_S",
    "_resolve_table_uri",
    "build_clone_command",
    "build_index_run_command",
    "build_prepare_scripts_args",
    "check_git_clone",
    "check_index_run_result",
    "create_index_run_step",
    "ensureIndexSandbox",
    "gitCloneToSandbox",
    "mark_index_run_error_step",
    "mark_index_run_running_step",
    "mark_index_run_success_step",
    "mark_repo_indexed_error_step",
    "mark_repo_indexed_success_step",
    "resolve_index_env",
    "runIndexPipeline",
    "stopIndexerSandbox",
    "uploadScriptsToSandbox",
]
