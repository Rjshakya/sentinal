"""Unit tests for the codegraph install + index step and search tool.

Pure workers only (command builders, summary parser, query argv,
worker error mapping with a stub backend, prompt wording) — no
sandbox, no DBOS, no network. The DBOS step edge is covered by
construction (same decorator pattern as every other v2 step).
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from app.services.agent_v2.prompts import SEARCH_CODEGRAPH_TOOL_DESCRIPTION
from app.services.sandbox.e2b_template import CODEGRAPH_PCK_NAME
from app.services.agent_v2.prompts.file_review import (
    createFileReviewSystemPrompt,
)
from app.services.agent_v2.prompts.planning import createPlanningSystemPrompt
from app.services.agent_v2.service import buildCodeGraphQueryCommand
from app.utils.branded import CommitId, PRNumber, RepoId, RepoName, UserId
from app.utils.util import graph_db_path, repo_path
from app.workflows.review_v2.errors import (
    CodeGraphIndexError,
    CodeGraphInstallTransientError,
)
from app.workflows.review_v2.steps.codegraph_index import (
    CodeGraphIndexResult,
    buildIndexCommand,
    buildInstallCommand,
    installCodeGraphAndIndexRepo,
    parseIndexSummary,
)


def test_install_command_pins_published_dist() -> None:
    command: str = buildInstallCommand()
    assert command.startswith("pip install ")
    assert CODEGRAPH_PCK_NAME in command
    assert CODEGRAPH_PCK_NAME == "sentinel-codegraph==0.3.0"


def test_index_command_targets_repo_and_fixed_db() -> None:
    repo: RepoName = RepoName("my-repo")
    command: str = buildIndexCommand(repoName=repo)
    assert command.startswith("codegraph index ")
    assert repo_path("my-repo") in command
    assert graph_db_path() in command
    assert "--overwrite" in command


def test_parse_index_summary_indexed() -> None:
    result: CodeGraphIndexResult = parseIndexSummary(
        "indexed 19 files, 351 nodes, 552 edges -> /tmp/g.lbdb [/root]"
    )
    assert (result.files, result.nodes, result.edges) == (19, 351, 552)


def test_parse_index_summary_scanned_with_skipped_suffix() -> None:
    result: CodeGraphIndexResult = parseIndexSummary(
        "scanned 4 files, 9 nodes, 12 edges -> :memory: [/r] (2 skipped)"
    )
    assert (result.files, result.nodes, result.edges) == (4, 9, 12)


def test_parse_index_summary_garbage_raises() -> None:
    with pytest.raises(ValueError):
        parseIndexSummary("pip installed ok\n")


def _stub_sandbox(responses: list[SimpleNamespace]) -> Any:
    """Backend stub replaying one ExecuteResponse per ``aexecute`` call."""

    class _Stub:
        def __init__(self) -> None:
            self.commands: list[str] = []

        async def aexecute(
            self, command: str, *, timeout: int | None = None
        ) -> SimpleNamespace:
            _ = timeout
            self.commands.append(command)
            return responses.pop(0)

    return _Stub()


def _ok_index_output() -> str:
    return "indexed 3 files, 9 nodes, 12 edges -> /db [/root]"


async def test_worker_install_then_index_ok() -> None:
    sandbox: Any = _stub_sandbox(
        [
            SimpleNamespace(exit_code=0, output="Successfully installed\n"),
            SimpleNamespace(exit_code=0, output=_ok_index_output()),
        ]
    )
    result = await installCodeGraphAndIndexRepo(
        sandbox,
        userId=UserId("u"),
        repoId=RepoId("r"),
        repoName=RepoName("my-repo"),
        prNumber=PRNumber(7),
        headSha=CommitId("abc123"),
    )
    assert isinstance(result, CodeGraphIndexResult)
    assert (result.files, result.nodes, result.edges) == (3, 9, 12)
    assert len(sandbox.commands) == 2
    assert sandbox.commands[0].startswith("pip install ")
    assert sandbox.commands[1].startswith("codegraph index ")


async def test_worker_pip_failure_is_transient() -> None:
    sandbox: Any = _stub_sandbox(
        [SimpleNamespace(exit_code=1, output="ERROR: No matching distribution\n")]
    )
    result = await installCodeGraphAndIndexRepo(
        sandbox,
        userId=UserId("u"),
        repoId=RepoId("r"),
        repoName=RepoName("my-repo"),
        prNumber=PRNumber(7),
        headSha=CommitId("abc123"),
    )
    assert isinstance(result, CodeGraphInstallTransientError)
    assert result.exitCode == 1
    assert len(sandbox.commands) == 1  # index never runs


async def test_worker_runner_dropout_is_transient() -> None:
    sandbox: Any = _stub_sandbox(
        [
            SimpleNamespace(exit_code=0, output="ok\n"),
            SimpleNamespace(exit_code=-1, output=""),
        ]
    )
    result = await installCodeGraphAndIndexRepo(
        sandbox,
        userId=UserId("u"),
        repoId=RepoId("r"),
        repoName=RepoName("my-repo"),
        prNumber=PRNumber(7),
        headSha=CommitId("abc123"),
    )
    assert isinstance(result, CodeGraphInstallTransientError)


async def test_worker_index_failure_is_final() -> None:
    sandbox: Any = _stub_sandbox(
        [
            SimpleNamespace(exit_code=0, output="ok\n"),
            SimpleNamespace(exit_code=2, output="error: path does not exist\n"),
        ]
    )
    result = await installCodeGraphAndIndexRepo(
        sandbox,
        userId=UserId("u"),
        repoId=RepoId("r"),
        repoName=RepoName("my-repo"),
        prNumber=PRNumber(7),
        headSha=CommitId("abc123"),
    )
    assert isinstance(result, CodeGraphIndexError)
    assert result.exitCode == 2


async def test_worker_unparseable_summary_is_final() -> None:
    sandbox: Any = _stub_sandbox(
        [
            SimpleNamespace(exit_code=0, output="ok\n"),
            SimpleNamespace(exit_code=0, output="something unexpected\n"),
        ]
    )
    result = await installCodeGraphAndIndexRepo(
        sandbox,
        userId=UserId("u"),
        repoId=RepoId("r"),
        repoName=RepoName("my-repo"),
        prNumber=PRNumber(7),
        headSha=CommitId("abc123"),
    )
    assert isinstance(result, CodeGraphIndexError)


def test_query_command_search() -> None:
    command: str | None = buildCodeGraphQueryCommand(
        verb="search", name="helper", file=None, node_id=None, limit=20
    )
    assert command is not None
    assert "--json" in command
    assert graph_db_path() in command
    assert "--name" in command and "helper" in command
    assert "--limit" in command


def test_query_command_drill_prefers_id() -> None:
    command: str | None = buildCodeGraphQueryCommand(
        verb="callees",
        name="run",
        file="a.py",
        node_id="a.py:run:1:5",
        limit=20,
    )
    assert command is not None
    assert "--id" in command and "a.py:run:1:5" in command


def test_query_command_drill_by_name_and_file() -> None:
    command: str | None = buildCodeGraphQueryCommand(
        verb="callers", name="run", file="a.py", node_id=None, limit=20
    )
    assert command is not None
    assert "--name" in command and "--file" in command


def test_query_command_overview_and_files_take_no_target() -> None:
    for verb in ("overview", "files"):
        command: str | None = buildCodeGraphQueryCommand(
            verb=verb, name=None, file=None, node_id=None, limit=20
        )
        assert command is not None
        assert verb in command.split()


def test_query_command_imports_needs_file_or_id() -> None:
    assert (
        buildCodeGraphQueryCommand(
            verb="imports", name=None, file="a.py", node_id=None, limit=20
        )
        is not None
    )
    assert (
        buildCodeGraphQueryCommand(
            verb="imports", name=None, file=None, node_id=None, limit=20
        )
        is None
    )


def test_query_command_rejects_unsatisfiable_verbs() -> None:
    assert (
        buildCodeGraphQueryCommand(
            verb="search", name=None, file=None, node_id=None, limit=20
        )
        is None
    )
    assert (
        buildCodeGraphQueryCommand(
            verb="node", name=None, file=None, node_id=None, limit=20
        )
        is None
    )


def test_query_command_quotes_values() -> None:
    command: str | None = buildCodeGraphQueryCommand(
        verb="search", name="my helper", file=None, node_id=None, limit=20
    )
    assert command is not None
    assert "'my helper'" in command


def test_tool_description_covers_ladder() -> None:
    for verb in (
        "files",
        "search",
        "node",
        "callees",
        "callers",
        "children",
        "imports",
        "overview",
    ):
        assert verb in SEARCH_CODEGRAPH_TOOL_DESCRIPTION


def test_prompts_direct_tool_first() -> None:
    planner: str = createPlanningSystemPrompt(
        repoName="r", userId="u", modelCallRunLimit=200, toolCallRunLimit=200
    )
    assert "search_codegraph" in planner
    file_prompt: str = createFileReviewSystemPrompt(
        repoName="r", userId="u", modelCallRunLimit=100, toolCallRunLimit=100
    )
    assert "search_codegraph" in file_prompt
    assert "Blast radius first" in file_prompt
