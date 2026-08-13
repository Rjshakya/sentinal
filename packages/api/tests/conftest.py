"""Shared fixtures for the indexing-pipeline e2e test."""

from __future__ import annotations

import asyncio
import sys
from uuid import uuid4

import pytest
from dbos import (
    DBOS,
    DBOSConfig,
    SetWorkflowID,
    WorkflowStatus,
    WorkflowStatusString,
)

# psycopg async (used by DBOS) fails on Windows' ProactorEventLoop —
# force the SelectorEventLoop, mirroring packages/api/main.py.
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from app.core.config import settings
from app.services.indexing.helpers import index_workflow_id
from app.services.indexing.types import IndexWorkflowInput
from app.services.indexing.workflow import indexRepo

INDEX_TIMEOUT_S: float = 2000.0

_TERMINAL_STATES = {
    WorkflowStatusString.SUCCESS.value,
    WorkflowStatusString.ERROR.value,
    WorkflowStatusString.MAX_RECOVERY_ATTEMPTS_EXCEEDED.value,
    WorkflowStatusString.CANCELLED.value,
}


def _dbos_config() -> DBOSConfig:
    db_url = settings.dbos_database_url
    return {
        "name": "sentinel",
        "system_database_url": db_url,
        "application_database_url": db_url,
        "executor_id": "pytest",
    }


@pytest.fixture(scope="session", autouse=True)
def e2b_templates() -> None:
    """Build the E2B sandbox templates the e2e tests need.

    Idempotent — ``Template.build`` returns the existing template id
    on subsequent calls. Skipped when ``E2B_API_KEY`` is unset so the
    fixture never hard-fails for tests that don't need a sandbox.
    """
    if settings.e2b_api_key:
        from app.core.sandbox.e2b import (
            build_e2b_index_template,
            build_e2b_template,
        )

        build_e2b_template()
        build_e2b_index_template()


@pytest.fixture(scope="session", autouse=True)
def dbos_lifecycle():
    """Launch DBOS against Postgres once per session; skip if unreachable."""
    DBOS(config=_dbos_config())
    try:
        DBOS.launch()
    except Exception as exc:  # noqa: BLE001 — session-skip path: any launch failure is a fixture-level skip
        pytest.skip(f"Postgres/DBOS unavailable ({type(exc).__name__}: {exc})")
    try:
        yield
    finally:
        DBOS.destroy()


@pytest.fixture(scope="session")
def workflow_salt() -> str:
    """Per-session uuid slice so repeated pytest runs re-execute the pipeline."""
    return uuid4().hex[:8]


@pytest.fixture
def requires_indexing_env() -> None:
    """Skip the test when the indexing pipeline is not configured.

    Requires the host env has the in-sandbox pipeline's full set of
    credentials: OpenAI key, E2B key, INDEX_S3_BUCKET, and the full
    AWS quartet (access key + secret + region + endpoint URL).
    """
    if not settings.indexing_configured:
        pytest.skip(
            "indexing e2e requires OPENAI_API_KEY, E2B_API_KEY, "
            "INDEX_S3_BUCKET, AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, "
            "AWS_REGION, AWS_ENDPOINT_URL"
        )


@pytest.fixture
def bucket_owner_repo() -> tuple[str, str, str]:
    """The (bucket, owner, repo) triple the e2e test writes to."""
    bucket = settings.index_s3_bucket
    if not bucket:
        pytest.skip("INDEX_S3_BUCKET is not set")
    # owner / repo derived from the default E2E repo below.
    return bucket, "", ""


async def run_index_workflow(
    input: IndexWorkflowInput,
    *,
    workflow_id: str | None = None,
    timeout_s: float = INDEX_TIMEOUT_S,
) -> tuple[str, WorkflowStatus]:
    """Dispatch ``indexRepo`` under its deterministic id; wait for a terminal state."""
    if workflow_id is None:
        workflow_id = index_workflow_id(input.repo_owner, input.repo_name)
    with SetWorkflowID(workflow_id):
        handle = await DBOS.start_workflow_async(indexRepo, input)
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_s
    while True:
        status = await DBOS.get_workflow_status_async(handle.workflow_id)
        if status is not None and status.status in _TERMINAL_STATES:
            return handle.workflow_id, status
        if loop.time() >= deadline:
            pytest.fail(f"indexRepo {handle.workflow_id} timed out after {timeout_s}s")
        await asyncio.sleep(2.0)
