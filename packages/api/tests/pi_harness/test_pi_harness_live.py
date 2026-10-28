"""Live-sandbox tests for the v3 pi harness.

Spins up a real E2B sandbox and drives
:func:`app.services.pi_harness.PiAgentHarness` end to end — no mocks,
no durable runtime. Requires ``E2B_API_KEY`` and ``LLM_API_KEY`` (an
opencode-go key); skips without them. Each ``--print`` run spends real
model credit and takes ~1-2 minutes.

Run: cd packages/api && uv run pytest tests/pi_harness/test_pi_harness_live.py -v
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import cast

import pytest
from deepagents.backends.protocol import ExecuteResponse
from deepagents.backends.sandbox import BaseSandbox
from typing_extensions import Protocol

from app.core.config import settings
from app.services.pi_harness import (
    PiAgentHarness,
    PiCostError,
    PiModel,
    PiRunResult,
    addTotalCosts,
    findCostsOfSession,
    getPiSessionCost,
    phaseSessionId,
)
from app.services.sandbox.errors import SandboxProviderError
from app.services.sandbox.service import createSandboxCtx, getProvider
from app.services.sandbox.types import ProviderId
from app.utils.branded import ApiKey, RepoId, UserId
from app.utils.branded import SanboxProviderApiKey

_TEST_PROVIDER = "opencode-go"
_TEST_MODEL = "muse-spark-1.3-contributor"
_TEST_USER = UserId("pi-harness-test")
_TEST_PR = 1
_TEST_SHA = "abcdef1234567890"
_TEST_EXTENSION = "npm:@ff-labs/pi-fff"


class _ExecBackend(Protocol):
    """The async exec surface the harness runs on."""

    async def aexecute(
        self, command: str, *, timeout: int | None = None
    ) -> ExecuteResponse: ...


def _require_live_env() -> tuple[str, str]:
    """Return ``(e2b_key, llm_key)``, skipping when the env is incomplete."""
    if not settings.e2b_api_key:
        pytest.skip("E2B_API_KEY is not set; live harness test needs it")
    if not settings.llm_api_key:
        pytest.skip("LLM_API_KEY is not set; live harness test needs it")
    return settings.e2b_api_key, settings.llm_api_key


def _testModel(llmKey: str) -> PiModel:
    """Model selection for every live run."""
    return PiModel(
        provider=_TEST_PROVIDER,
        modelId=_TEST_MODEL,
        apiKey=ApiKey(llmKey),
    )


@pytest.fixture
async def backend() -> AsyncIterator[_ExecBackend]:
    """Ephemeral E2B backend, destroyed after the test (best-effort)."""
    e2b_key, _ = _require_live_env()
    sandboxCtx = createSandboxCtx(
        userId=_TEST_USER,
        repoId=RepoId("pi-harness"),
        repoName="pi-harness",
        providerId=cast(ProviderId, settings.sandbox_provider),
        apiKey=SanboxProviderApiKey(e2b_key),
        sandboxName="pi-harness-sandbox",
        rootPath="/home/user",
    )
    provider = getProvider(sandboxCtx.providerId)
    raw = await provider(ctx=sandboxCtx).create()
    if isinstance(raw, SandboxProviderError):
        pytest.fail(f"sandbox create failed: {raw.message}")
    execBackend = cast(_ExecBackend, cast(BaseSandbox, raw))
    await execBackend.aexecute("mkdir -p /home/user/.sentinel", timeout=60)
    try:
        yield execBackend
    finally:
        try:
            await provider(ctx=sandboxCtx).kill()
        except Exception:
            pass


async def test_pi_present(backend: _ExecBackend) -> None:
    """The ``pi`` CLI is installed in the sandbox."""
    ran = await backend.aexecute("pi --version", timeout=60)
    assert ran.exit_code == 0, f"pi --version failed: {ran.output!r}"


async def test_tools_flags_live(backend: _ExecBackend) -> None:
    """Custom tools + excluded tools render and are accepted by pi."""
    _, llm_key = _require_live_env()
    harness = (
        PiAgentHarness(
            sessionId=phaseSessionId(
                prNumber=_TEST_PR, headSha=_TEST_SHA, phase="tools"
            ),
            model=_testModel(llm_key),
        )
        .setTools(["read", "grep", "find", "ls", "codemode"])
        .excludeTools(["write"])
    )
    command = harness.buildCommand("Reply with exactly: TOOLS_OK")
    assert "--tools" in command and "codemode" in command
    assert "--exclude-tools" in command and "write" in command

    result = await harness.run("Reply with exactly: TOOLS_OK", backend)
    assert result.ok, f"pi --print with tools failed: {result.error}"
    assert result.text is not None and "TOOLS_OK" in result.text


async def test_append_system_prompt_live(backend: _ExecBackend) -> None:
    """Repeatable ``--append-system-prompt`` renders and runs."""
    _, llm_key = _require_live_env()
    harness = (
        PiAgentHarness(
            sessionId=phaseSessionId(
                prNumber=_TEST_PR, headSha=_TEST_SHA, phase="prompt"
            ),
            model=_testModel(llm_key),
        )
        .appendSystemPrompt("Always be concise.")
        .appendSystemPrompt("Never invent file names.")
    )
    command = harness.buildCommand("hi")
    assert command.count("--append-system-prompt") == 2

    result = await harness.run("Reply with exactly: PROMPT_OK", backend)
    assert result.ok, f"pi --print with prompts failed: {result.error}"
    assert result.text is not None and "PROMPT_OK" in result.text


async def test_extension_install_uninstall(backend: _ExecBackend) -> None:
    """``pi install`` runs aggregated; uninstall cleans up afterwards."""
    _require_live_env()
    harness = PiAgentHarness(
        sessionId=phaseSessionId(prNumber=_TEST_PR, headSha=_TEST_SHA, phase="ext"),
        model=_testModel("dummy-key-for-install-only"),
    ).addExtension(_TEST_EXTENSION)

    installCommand = harness.buildInstallCommand()
    assert installCommand is not None
    assert installCommand.count("pi install") == 1
    assert _TEST_EXTENSION in installCommand

    installed = await backend.aexecute(installCommand, timeout=300)
    assert installed.exit_code == 0, (
        f"pi install failed: {installed.output!r}\n"
        f"hint: check the exact install/list syntax via `pi --help`"
    )

    mainCommand = harness.buildCommand("hi")
    assert f"--extension {_TEST_EXTENSION}" in mainCommand

    uninstalled = await backend.aexecute(
        f"pi uninstall {_TEST_EXTENSION}", timeout=300
    )
    assert uninstalled.exit_code == 0, (
        f"pi uninstall failed: {uninstalled.output!r}\n"
        f"hint: check the exact uninstall syntax via `pi --help`"
    )


async def test_print_e2e(backend: _ExecBackend) -> None:
    """Full ``pi --print`` run: flags, stdout text, key scrub, session echo."""
    _, llm_key = _require_live_env()
    sessionId = phaseSessionId(
        prNumber=_TEST_PR, headSha=_TEST_SHA, phase="print"
    )
    harness = PiAgentHarness(sessionId=sessionId, model=_testModel(llm_key))

    command = harness.buildCommand("Reply with exactly: SENTINEL_OK")
    for flag in (
        "--print",
        "-p",
        "--provider",
        _TEST_PROVIDER,
        "--model",
        _TEST_MODEL,
        "--session-id",
        sessionId,
    ):
        assert flag in command, f"missing {flag!r} in built command"
    assert "--mode json" not in command

    result: PiRunResult = await harness.run(
        "Reply with exactly: SENTINEL_OK", backend
    )
    assert result.ok, f"pi --print failed: {result.error}"
    assert result.text is not None and "SENTINEL_OK" in result.text
    assert result.sessionId == sessionId
    assert llm_key not in result.text

    cost = await getPiSessionCost(backend, sessionId=sessionId)
    assert not isinstance(cost, PiCostError), f"cost read failed: {cost.message}"
    assert cost.input > 0 and cost.total >= cost.input + cost.output


async def test_session_cost_accumulates(backend: _ExecBackend) -> None:
    """Two runs sharing one session id accumulate cost in one file."""
    _, llm_key = _require_live_env()
    sessionId = phaseSessionId(
        prNumber=_TEST_PR, headSha=_TEST_SHA, phase="cost-accum"
    )
    harness = PiAgentHarness(sessionId=sessionId, model=_testModel(llm_key))

    first = await harness.run("Reply with exactly: COST_ONE", backend)
    assert first.ok, f"first run failed: {first.error}"
    assert first.text is not None and "COST_ONE" in first.text
    cost1 = await getPiSessionCost(backend, sessionId=sessionId)
    assert not isinstance(cost1, PiCostError), f"cost1 read failed: {cost1.message}"
    assert cost1.input > 0

    second = await harness.run("Reply with exactly: COST_TWO", backend)
    assert second.ok, f"second run failed: {second.error}"
    assert second.text is not None and "COST_TWO" in second.text
    cost2 = await getPiSessionCost(backend, sessionId=sessionId)
    assert not isinstance(cost2, PiCostError), f"cost2 read failed: {cost2.message}"
    assert cost2.input > cost1.input and cost2.total > cost1.total

    entries = await findCostsOfSession(backend, sessionId=sessionId)
    assert not isinstance(entries, PiCostError), (
        f"entries read failed: {entries.message}"
    )
    assert len(entries) >= 2


async def test_session_cost_unknown_id(backend: _ExecBackend) -> None:
    """A session id that never ran yields a cost error, not a crash."""
    _require_live_env()
    cost = await getPiSessionCost(backend, sessionId="never-ran-0000")
    assert isinstance(cost, PiCostError)


async def test_session_cost_survives_garbage(backend: _ExecBackend) -> None:
    """A corrupted line in a real session file does not break the read."""
    _, llm_key = _require_live_env()
    sessionId = phaseSessionId(
        prNumber=_TEST_PR, headSha=_TEST_SHA, phase="cost-garbage"
    )
    harness = PiAgentHarness(sessionId=sessionId, model=_testModel(llm_key))

    ran = await harness.run("Reply with exactly: GARBAGE_OK", backend)
    assert ran.ok, f"run failed: {ran.error}"
    before = await getPiSessionCost(backend, sessionId=sessionId)
    assert not isinstance(before, PiCostError), f"cost read failed: {before.message}"

    found = await backend.aexecute(
        f"find ~/.pi/agent/sessions -name '*_{sessionId}.jsonl'", timeout=60
    )
    assert found.exit_code == 0 and found.output.strip(), "no session file found"
    polluted = await backend.aexecute(
        f"echo 'not json at all' >> {found.output.strip().splitlines()[0].strip()}",
        timeout=60,
    )
    assert polluted.exit_code == 0

    after = await getPiSessionCost(backend, sessionId=sessionId)
    assert after == before


async def test_session_cost_cwd_scoping(backend: _ExecBackend) -> None:
    """Same session id from two workdirs scopes reads per cwd."""
    _, llm_key = _require_live_env()
    sessionId = phaseSessionId(
        prNumber=_TEST_PR, headSha=_TEST_SHA, phase="cost-scope"
    )
    otherDir = "/home/user/.sentinel-other"
    await backend.aexecute(f"mkdir -p {otherDir}", timeout=60)

    near = PiAgentHarness(sessionId=sessionId, model=_testModel(llm_key))
    first = await near.run("Reply with exactly: SCOPE_NEAR", backend)
    assert first.ok, f"near run failed: {first.error}"

    far = PiAgentHarness(
        sessionId=sessionId, model=_testModel(llm_key), workDir=otherDir
    )
    second = await far.run("Reply with exactly: SCOPE_FAR", backend)
    assert second.ok, f"far run failed: {second.error}"

    nearEntries = await findCostsOfSession(backend, sessionId=sessionId)
    assert not isinstance(nearEntries, PiCostError)
    farEntries = await findCostsOfSession(
        backend, sessionId=sessionId, workDir=otherDir
    )
    assert not isinstance(farEntries, PiCostError)
    assert len(nearEntries) >= 1 and len(farEntries) >= 1
    assert addTotalCosts(nearEntries) != addTotalCosts(farEntries)


__all__ = [
    "test_append_system_prompt_live",
    "test_extension_install_uninstall",
    "test_pi_present",
    "test_print_e2e",
    "test_session_cost_accumulates",
    "test_session_cost_cwd_scoping",
    "test_session_cost_survives_garbage",
    "test_session_cost_unknown_id",
    "test_tools_flags_live",
]
