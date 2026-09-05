"""Shared fixtures for the indexing- and review-pipeline e2e tests."""

from __future__ import annotations

import asyncio
import os
import sys
from uuid import uuid4
from pathlib import Path
import pytest
from dbos import (
    DBOS,
    DBOSConfig,
    SetWorkflowID,
    WorkflowStatus,
    WorkflowStatusString,
)

# BASE_DIR = Path(__file__).resolve().parents[3]
# ENV_PATH = BASE_DIR / ".env"
#
# load_dotenv(ENV_PATH, override=False)
# psycopg async (used by DBOS) fails on Windows' ProactorEventLoop —
# force the SelectorEventLoop, mirroring packages/api/main.py.


# if sys.platform == "win32":
#     asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


from app.core.config import settings
from app.core.db import create_db_and_tables
from app.services.indexing.helpers import index_workflow_id
from app.services.indexing.types import IndexWorkflowInput
from app.services.indexing.workflow import indexRepo
from app.workflows.review.types import (
    ReviewRunResult,
    ReviewWorkflowCtx,
    ReviewWorkflowInput,
)
from app.workflows.review.workflow import reviewWorkflow

INDEX_TIMEOUT_S: float = 2000.0
REVIEW_TIMEOUT_S: float = 1200.0

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


# @pytest.fixture(scope="session", autouse=True)
# def e2b_templates() -> None:
#     """Build the E2B sandbox templates the e2e tests need.
#
#     Idempotent — ``Template.build`` returns the existing template id
#     on subsequent calls. Skipped when ``E2B_API_KEY`` is unset so the
#     fixture never hard-fails for tests that don't need a sandbox.
#     """
#     if settings.e2b_api_key:
#         from app.core.sandbox.e2b import (
#             build_e2b_index_template,
#             build_e2b_template,
#         )
#
#         build_e2b_template()
#         build_e2b_index_template()
#


@pytest.fixture(scope="session", autouse=True)
async def dbos_lifecycle():
    """Launch DBOS against Postgres once per session; skip if unreachable.

    Runs on the pytest-asyncio session loop (see
    ``asyncio_default_*_loop_scope`` in ``pyproject.toml``) so the
    engine's pooled connections are created and reused on a single loop.
    """
    DBOS(config=_dbos_config())
    try:
        DBOS.launch()
    except (
        Exception
    ) as exc:  # noqa: BLE001 — session-skip path: any launch failure is a fixture-level skip
        pytest.skip(f"Postgres/DBOS unavailable ({type(exc).__name__}: {exc})")
    try:
        await create_db_and_tables()
    except (
        Exception
    ) as exc:  # noqa: BLE001 — session-skip path: cannot create app tables
        pytest.skip(f"cannot create app tables ({type(exc).__name__}: {exc})")
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
def requires_review_env() -> None:
    """Skip the review e2e when its env prerequisites are missing.

    Requires the review pipeline's full credential set: an LLM key,
    the sandbox (E2B) key, the GitHub App identity (the clone mints an
    installation token), an OpenAI key (the structured extractor is
    OpenAI-only), and a live ``REVIEW_E2E_INSTALLATION_ID`` for the
    target repo.
    """
    if not settings.llm_configured:
        pytest.skip("review e2e requires LLM_MODEL + LLM_API_KEY")
    if not settings.sandbox_configured:
        pytest.skip("review e2e requires the sandbox provider key")
    if not settings.github_app_configured:
        pytest.skip("review e2e requires the GitHub App credentials")
    if not (settings.openai_api_key or os.environ.get("OPENAI_API_KEY")):
        pytest.skip("review e2e requires an OpenAI key (extractor)")
    if not settings.review_e2e_installation_id:
        pytest.skip("review e2e requires REVIEW_E2E_INSTALLATION_ID")


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
    status = await handle.get_status()
    return handle.workflow_id, status


async def run_review_workflow(
    ctx: ReviewWorkflowCtx,
    input: ReviewWorkflowInput,
    *,
    workflow_id: str,
    timeout_s: float = REVIEW_TIMEOUT_S,
) -> tuple[str, ReviewRunResult, WorkflowStatus]:
    """Dispatch ``reviewWorkflow`` under its deterministic id; wait for a terminal state."""
    with SetWorkflowID(workflow_id):
        handle = await DBOS.start_workflow_async(reviewWorkflow, ctx, input)
    output = await handle.get_result()
    status = await handle.get_status()
    return handle.workflow_id, output, status
