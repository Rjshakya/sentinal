"""Live index + query tests for the codegraph CLI on a real repo.

Boots one sandbox from the pre-baked template, shallow-clones
cal.diy (full history is 16.5k commits — ``--depth 1`` keeps the
clone tractable), indexes it, and queries the resulting graph.
Like the rest of this dir these hit real E2B infrastructure and need
``E2B_API_KEY``.

Layout:

- ``caldiy_sandbox`` (module fixture) — create → shallow clone →
  yield → kill. The index and query tests share this sandbox so the
  repo is cloned and indexed once.
- ``test_index_cal_diy`` — runs ``codegraph index`` with no ``--db``
  flag (codegraph resolves its default location), measures
  wall-clock time (logged, no threshold), parses the summary, and
  asserts files were indexed.
- ``test_query_cal_diy`` — builds both query argv with the
  production ``buildCodeGraphQueryCommand`` (the same builder the
  ``search_codegraph`` tool uses), runs them, and asserts
  structurally: valid JSON, non-empty file list.

The query test runs after the index test in file order against the
same sandbox/DB.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import AsyncIterator

import pytest
from e2b import AsyncSandbox
from e2b.sandbox.commands.command_handle import CommandExitException

from app.core.config import settings
from app.services.agent_v2.service import buildCodeGraphQueryCommand
from app.services.sandbox.e2b_template import CODE_SANDBOX_TEMPLATE_NAME
from app.utils.util import sandbox_home
from app.workflows.review_v2.steps.codegraph_index import parseIndexSummary

log = logging.getLogger(__name__)

_CAL_DIY_URL: str = "https://github.com/calcom/cal.diy"
_CAL_DIY_DIR: str = f"{sandbox_home()}/cal.diy"

_CLONE_TIMEOUT_S: int = 600
"""Upper bound on the shallow clone of cal.diy."""

_INDEX_TIMEOUT_S: int = 1500
"""Upper bound on indexing the full cal.diy tree (generous on purpose)."""

_QUERY_TIMEOUT_S: int = 120
"""Upper bound on one in-sandbox ``codegraph query`` (local reads)."""


@pytest.fixture(scope="module")
async def caldiy_sandbox() -> AsyncIterator[AsyncSandbox]:
    sandbox = await AsyncSandbox.create(
        template=CODE_SANDBOX_TEMPLATE_NAME,
        api_key=settings.e2b_api_key,
        timeout=_CLONE_TIMEOUT_S,
    )
    try:
        clone = await sandbox.commands.run(
            f"git clone --depth 1 {_CAL_DIY_URL} {_CAL_DIY_DIR}",
            timeout=_CLONE_TIMEOUT_S,
        )
    except CommandExitException as exc:
        await sandbox.kill()
        pytest.fail(
            "cal.diy clone failed: "
            f"exit={exc.exit_code} stderr={exc.stderr.strip()}"
        )
    _ = clone
    try:
        yield sandbox
    finally:
        await sandbox.kill()


async def test_index_cal_diy(caldiy_sandbox: AsyncSandbox) -> None:
    try:
        started: float = time.perf_counter()
        indexed = await caldiy_sandbox.commands.run(
            f"codegraph index {_CAL_DIY_DIR} --overwrite",
            timeout=_INDEX_TIMEOUT_S,
        )
        elapsed_s: float = time.perf_counter() - started
    except CommandExitException as exc:
        pytest.fail(
            "codegraph index failed: "
            f"exit={exc.exit_code} stderr={exc.stderr.strip()}"
        )
    log.info("codegraph index of cal.diy took %.1fs", elapsed_s)
    result = parseIndexSummary(indexed.stdout)
    log.info(
        "index summary: files=%d nodes=%d edges=%d",
        result.files,
        result.nodes,
        result.edges,
    )
    assert result.files > 0


async def test_query_cal_diy(caldiy_sandbox: AsyncSandbox) -> None:
    files_command: str | None = buildCodeGraphQueryCommand(
        verb="files", name=None, file=None, node_id=None, limit=20
    )
    assert files_command is not None
    search_command: str | None = buildCodeGraphQueryCommand(
        verb="search", name="booking", file=None, node_id=None, limit=5
    )
    assert search_command is not None

    try:
        files_out = await caldiy_sandbox.commands.run(
            files_command, timeout=_QUERY_TIMEOUT_S
        )
        search_out = await caldiy_sandbox.commands.run(
            search_command, timeout=_QUERY_TIMEOUT_S
        )
    except CommandExitException as exc:
        pytest.fail(
            "codegraph query failed: "
            f"exit={exc.exit_code} stderr={exc.stderr.strip()}"
        )

    files = json.loads(files_out.stdout)
    assert isinstance(files, list) and len(files) > 0

    search_hits = json.loads(search_out.stdout)
    assert isinstance(search_hits, (list, dict))
