"""V3 pi agent harness: build ``pi`` CLI commands, run them in a sandbox.

:class:`PiAgentHarness` is a mutable fluent builder. It accumulates
options, renders them to one shell command with :meth:`buildCommand`
(pure — unit-testable without a sandbox), and executes it with
:meth:`run` (``pi --print``, plain stdout as :class:`PiRunResult` text).

Fixed on every command: ``--print``, ``--session-id``, ``-na`` (distrust the
reviewed repo's project config), ``-nc`` (no AGENTS.md/CLAUDE.md
discovery — prompt-injection guard). ``--approve`` only via
:meth:`trustProject`. :meth:`run` never raises; failures fold into
:class:`PiRunResult`. The API key is scrubbed from all outputs and
errors. :meth:`buildCommand` raises :class:`ValueError` on a bad
session id (programmer error).

Working directory: the sentinel root (``/home/user/.sentinel``) so one
run sees both ``./{repo}/`` and ``./{head_sha}/diff/``. Extension specs
added via :meth:`addExtension` are installed once via an aggregated
``pi install`` command at the start of :meth:`run`, then referenced
with repeatable ``--extension`` on the main command. The system prompt
is append-only (:meth:`appendSystemPrompt`); there is no replace.
"""

from __future__ import annotations

import re
import shlex
from typing import Self

from deepagents.backends.protocol import ExecuteResponse
from typing_extensions import Protocol

from app.services.llm_config.types import LLMConfigCtx
from app.services.pi_harness.types import (
    DEFAULT_TOOLS,
    PiModel,
    PiRunResult,
    ThinkingLevel,
)
from app.utils.branded import ApiKey
from app.utils.sandbox_fs import sentinelRoot

_SESSION_ID_RE = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?")
_ERROR_CHARS = 500


class _ExecBackend(Protocol):
    """The async exec surface the harness runs on."""

    async def aexecute(
        self, command: str, *, timeout: int | None = None
    ) -> ExecuteResponse: ...


def validateSessionId(sessionId: str) -> str:
    """Validate a ``pi --session-id`` value (charset + alnum ends)."""
    if not sessionId or _SESSION_ID_RE.fullmatch(sessionId) is None:
        raise ValueError(
            "sessionId must start/end alphanumerically "
            f"([A-Za-z0-9._-]): {sessionId!r}"
        )
    return sessionId


def phaseSessionId(*, prNumber: int, headSha: str, phase: str) -> str:
    """Build a deterministic per-phase session id (distinct ids per phase)."""
    return validateSessionId(f"sentinel-{prNumber}-{headSha[:7]}-{phase}")


def modelFromCtx(
    ctx: LLMConfigCtx, *, thinking: ThinkingLevel | None = None
) -> PiModel:
    """Project an :class:`LLMConfigCtx` onto a :class:`PiModel`."""
    return PiModel(
        provider=ctx.provider,
        modelId=ctx.modelId,
        apiKey=ctx.apiKey,
        thinking=thinking,
    )


class PiAgentHarness:
    """Fluent builder for one phased pi run (one instance per phase)."""

    def __init__(
        self,
        workDir: str | None = None,
        *,
        sessionId: str,
        model: PiModel,
        name: str | None = None,
    ) -> None:
        resolved = workDir if workDir else sentinelRoot()
        if not resolved:
            raise ValueError("workDir must be non-empty")
        self._workDir = resolved
        self._sessionId = validateSessionId(sessionId)
        self._model = model
        self._name = name
        self._appendedPrompts: list[str] = []
        self._tools: list[str] = list(DEFAULT_TOOLS)
        self._excludedTools: list[str] = []
        self._extensions: list[str] = []
        self._skills: list[str] = []
        self._noSkills = False
        self._approve = False

    def setModel(
        self,
        provider: str,
        modelId: str,
        apiKey: ApiKey,
        *,
        thinking: ThinkingLevel | None = None,
    ) -> Self:
        """Replace the model selection."""
        self._model = PiModel(
            provider=provider,
            modelId=modelId,
            apiKey=apiKey,
            thinking=thinking,
        )
        return self

    def setSessionId(self, sessionId: str) -> Self:
        """Replace the session id (validated)."""
        self._sessionId = validateSessionId(sessionId)
        return self

    def appendSystemPrompt(self, text: str) -> Self:
        """Append to the system prompt (repeatable ``--append-system-prompt``)."""
        self._appendedPrompts.append(text)
        return self

    def setTools(self, tools: list[str]) -> Self:
        """Replace the tool allowlist (``--tools``)."""
        self._tools = list(tools)
        return self

    def excludeTools(self, tools: list[str]) -> Self:
        """Disable tools after selection (``--exclude-tools``)."""
        self._excludedTools = list(tools)
        return self

    def addExtension(self, spec: str) -> Self:
        """Register an extension spec for ``pi install`` (repeatable).

        Specs are installed once via one aggregated ``pi install`` call
        at the start of :meth:`run`, then referenced with repeatable
        ``--extension`` on the main command.
        """
        if not spec:
            raise ValueError("extension spec must be non-empty")
        self._extensions.append(spec)
        return self

    def addSkill(self, path: str) -> Self:
        """Load a skill file/dir (repeatable ``--skill``)."""
        self._skills.append(path)
        return self

    def noSkills(self) -> Self:
        """Disable discovered skills (explicit ``--skill`` still loads)."""
        self._noSkills = True
        return self

    def trustProject(self) -> Self:
        """Trust project-local config for this run (``--approve``)."""
        self._approve = True
        return self

    def buildInstallCommand(self) -> str | None:
        """Render the aggregated ``pi install`` command, if extensions exist.

        Pure; ``None`` when no extensions were added. Installs run before
        the main command in :meth:`run` (single round-trip for all specs).
        """
        if not self._extensions:
            return None
        steps = " && ".join(f"pi install {shlex.quote(ext)}" for ext in self._extensions)
        return f"cd {shlex.quote(self._workDir)} && {steps}"

    def buildCommand(self, prompt: str) -> str:
        """Render the full shell command (pure; ``cd`` into the work dir first)."""
        parts: list[str] = [
            "pi",
            "--print",
            "--session-id",
            shlex.quote(self._sessionId),
            "--provider",
            shlex.quote(self._model.provider),
            "--model",
            shlex.quote(self._model.modelId),
            "--api-key",
            shlex.quote(str(self._model.apiKey)),
        ]
        if self._model.thinking is not None:
            parts += ["--thinking", shlex.quote(self._model.thinking)]
        if self._name is not None:
            parts += ["--name", shlex.quote(self._name)]
        for extra in self._appendedPrompts:
            parts += ["--append-system-prompt", shlex.quote(extra)]
        if self._tools:
            parts += ["--tools", shlex.quote(",".join(self._tools))]
        if self._excludedTools:
            parts += ["--exclude-tools", shlex.quote(",".join(self._excludedTools))]
        for ext in self._extensions:
            parts += ["--extension", shlex.quote(ext)]
        for skill in self._skills:
            parts += ["--skill", shlex.quote(skill)]
        if self._noSkills:
            parts += ["-ns"]
        parts += ["-na", "-nc"]
        if self._approve:
            parts += ["-a"]
        parts += ["-p", shlex.quote(prompt)]
        return f"cd {shlex.quote(self._workDir)} && {' '.join(parts)}"

    async def run(
        self,
        prompt: str,
        backend: _ExecBackend,
        *,
        timeoutS: int = 600,
    ) -> PiRunResult:
        """Install extensions (one aggregated call), run ``pi --print``.

        Never raises: every failure folds into :class:`PiRunResult`.
        ``sessionId`` echoes the requested id whenever the main command
        was executed; it is ``None`` when the run never reached it
        (transport error or install-phase failure).
        """
        apiKey = str(self._model.apiKey)
        installCommand = self.buildInstallCommand()
        if installCommand is not None:
            try:
                installed = await backend.aexecute(
                    installCommand, timeout=timeoutS
                )
            except Exception as exc:
                return PiRunResult(
                    ok=False,
                    text=None,
                    sessionId=None,
                    error=f"pi install failed: {type(exc).__name__}: {exc}",
                )
            if installed.exit_code != 0:
                detail = _scrub(installed.output, apiKey=apiKey)[:_ERROR_CHARS]
                detail = detail or f"exit code {installed.exit_code}"
                return PiRunResult(
                    ok=False,
                    text=None,
                    sessionId=None,
                    error=f"pi install exited {installed.exit_code}: {detail}",
                )
        try:
            ran = await backend.aexecute(self.buildCommand(prompt), timeout=timeoutS)
        except Exception as exc:
            return PiRunResult(
                ok=False,
                text=None,
                sessionId=None,
                error=f"pi exec failed: {type(exc).__name__}: {exc}",
            )
        return _parsePrintResult(ran, apiKey=apiKey, sessionId=self._sessionId)


def _scrub(text: str, *, apiKey: str) -> str:
    """Strip output and redact the API key."""
    cleaned = (text or "").strip()
    if apiKey:
        cleaned = cleaned.replace(apiKey, "***")
    return cleaned


def _parsePrintResult(
    ran: ExecuteResponse, *, apiKey: str, sessionId: str
) -> PiRunResult:
    """Fold one ``pi --print`` execution into a result value (pure)."""
    if ran.exit_code != 0:
        detail = _scrub(ran.output, apiKey=apiKey)[:_ERROR_CHARS]
        detail = detail or f"exit code {ran.exit_code}"
        return PiRunResult(
            ok=False,
            text=None,
            sessionId=sessionId,
            error=f"pi exited {ran.exit_code}: {detail}",
        )
    text = _scrub(ran.output, apiKey=apiKey)
    if not text:
        return PiRunResult(
            ok=False,
            text=None,
            sessionId=sessionId,
            error="pi produced no output",
        )
    return PiRunResult(ok=True, text=text, sessionId=sessionId, error=None)


__all__ = [
    "PiAgentHarness",
    "modelFromCtx",
    "phaseSessionId",
    "validateSessionId",
]
