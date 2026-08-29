"""End-to-end test for the indexing pipeline.

Inputs (env): INDEX_E2E_REPO_URL, INDEX_E2E_REPO_OWNER,
INDEX_E2E_REPO_NAME, INDEX_E2E_DEFAULT_BRANCH.
Run: cd packages/api && uv run pytest tests/test_indexing_e2e.py -v
"""

from __future__ import annotations

import os

from conftest import run_index_workflow
from dbos import WorkflowStatusString

from app.services.indexing.helpers import index_workflow_id
from app.services.indexing.types import IndexRunResult, IndexWorkflowInput

E2E_REPO_URL = os.environ.get(
    "INDEX_E2E_REPO_URL",
    "https://github.com/Rjshakya/planetform",
)
E2E_REPO_OWNER = os.environ.get("INDEX_E2E_REPO_OWNER", "Rjshakya")
E2E_REPO_NAME = os.environ.get("INDEX_E2E_REPO_NAME", "planetform")
E2E_REPO_LOCAL_ID = os.environ.get(
    "INDEX_E2E_REPO_LOCAL_ID",
    "e2e-test-repo-00000000-0000-0000-0000-000000000000",
)
E2E_DEFAULT_BRANCH = os.environ.get("INDEX_E2E_DEFAULT_BRANCH", "main")


async def test_index_workflow_end_to_end(
    workflow_salt: str,
) -> None:
    """Full pipeline: sandbox -> clone -> chunk -> LanceDB write (in-sandbox)."""
    owner = E2E_REPO_OWNER
    repo = E2E_REPO_NAME
    workflow_id = f"{index_workflow_id(owner, repo)}:{workflow_salt}"

    actual_id, status = await run_index_workflow(
        IndexWorkflowInput(
            user_id="e2e-test-user",
            repo_owner=owner,
            repo_name=repo,
            repo_url=E2E_REPO_URL,
            default_branch=E2E_DEFAULT_BRANCH,
            local_repo_id=E2E_REPO_LOCAL_ID,
        ),
        workflow_id=workflow_id,
    )

    assert actual_id == workflow_id
    assert actual_id.startswith(f"index:{owner}:{repo}:")
    assert status.status == WorkflowStatusString.SUCCESS.value

    output = status.output
    assert output is not None
    result: IndexRunResult = output
    assert result.error_name is None
    assert result.error_message is None
    assert result.chunk_count > 0
    assert result.file_count >= 1
