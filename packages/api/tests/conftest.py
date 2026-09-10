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
        "executor_id": "pytest",
    }


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
