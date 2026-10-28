"""Read pi session costs from ``~/.pi/agent`` session files.

pi persists every run as JSONL under
``~/.pi/agent/sessions/<encoded-cwd>/<timestamp>_<sessionId>.jsonl``.
Assistant records carry ``message.usage`` (``input`` / ``output`` /
``cacheRead`` / ``cacheWrite`` / ``totalTokens``); this module finds a
session file by id, extracts those per-message costs, and folds them
into one :class:`PiSessionCost` total.

- :func:`getPiSessionCost` — find + fold (async, sandbox exec).
- :func:`findCostsOfSession` — locate + parse (async, sandbox exec).
- :func:`addTotalCosts` — pure sum (sync, unit-testable).

Lookup is by filename glob (``*_<sessionId>.jsonl``), so pi's
cwd-dir encoding never needs replicating. When several files match one
id, the session record's ``cwd`` prefers the run's ``workDir``.
Expected failures fold into :class:`PiCostError`, never raised.
``sessionId`` is validated (programmer error raises
:class:`ValueError`).
"""

from __future__ import annotations

import json
import shlex
from typing import Any

from deepagents.backends.protocol import ExecuteResponse
from typing_extensions import Protocol

from app.services.pi_harness.errors import PiCostError
from app.services.pi_harness.harness import validateSessionId
from app.services.pi_harness.types import PiSessionCost
from app.utils.sandbox_fs import sentinelRoot

_SESSIONS_REL = ".pi/agent/sessions"
_ERROR_CHARS = 200


class _ExecBackend(Protocol):
    """The async exec surface cost reads run on."""

    async def aexecute(
        self, command: str, *, timeout: int | None = None
    ) -> ExecuteResponse: ...


def addTotalCosts(costs: list[PiSessionCost]) -> PiSessionCost:
    """Fold per-message costs into one total (pure)."""
    total = PiSessionCost()
    for cost in costs:
        total = PiSessionCost(
            input=total.input + cost.input,
            output=total.output + cost.output,
            cacheRead=total.cacheRead + cost.cacheRead,
            cacheWrite=total.cacheWrite + cost.cacheWrite,
            total=total.total + cost.total,
        )
    return total


def _asInt(value: Any) -> int:
    """Coerce a token count; missing / null / non-int folds to 0."""
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _parseSessionFile(
    text: str, *, sessionId: str
) -> tuple[list[PiSessionCost], str | None] | PiCostError:
    """Extract per-assistant-message costs + the session cwd (pure).

    Returns ``(costs, cwd)`` for the file whose ``session`` record id
    matches, else :class:`PiCostError`. Malformed lines are skipped;
    a missing ``usage`` object skips that message.
    """
    matched = False
    cwd: str | None = None
    costs: list[PiSessionCost] = []
    for rawLine in text.split("\n"):
        line = rawLine.strip()
        if not line:
            continue
        try:
            record: Any = json.loads(line)
        except Exception:
            continue
        if not isinstance(record, dict):
            continue
        if record.get("type") == "session":
            if record.get("id") == sessionId:
                matched = True
                rawCwd = record.get("cwd")
                cwd = rawCwd if isinstance(rawCwd, str) else None
        elif record.get("type") == "message":
            message = record.get("message")
            if not isinstance(message, dict) or message.get("role") != "assistant":
                continue
            usage = message.get("usage")
            if not isinstance(usage, dict):
                continue
            costs.append(
                PiSessionCost(
                    input=_asInt(usage.get("input")),
                    output=_asInt(usage.get("output")),
                    cacheRead=_asInt(usage.get("cacheRead")),
                    cacheWrite=_asInt(usage.get("cacheWrite")),
                    total=_asInt(usage.get("totalTokens")),
                )
            )
    if not matched:
        return PiCostError(message=f"no pi session record for id {sessionId!r}")
    return (costs, cwd)


async def findCostsOfSession(
    backend: _ExecBackend,
    *,
    sessionId: str,
    workDir: str | None = None,
    timeoutS: int = 60,
) -> list[PiSessionCost] | PiCostError:
    """Locate the session file(s) and extract per-message costs."""
    sessionId = validateSessionId(sessionId)
    resolved = workDir if workDir else sentinelRoot()
    if not resolved:
        raise ValueError("workDir must be non-empty")
    try:
        found = await backend.aexecute(
            f"find $HOME/{_SESSIONS_REL} -name {shlex.quote(f'*_{sessionId}.jsonl')}",
            timeout=timeoutS,
        )
    except Exception as exc:
        return PiCostError(
            message=f"pi session lookup failed: {type(exc).__name__}: {exc}"
        )
    if found.exit_code != 0:
        detail = found.output.strip()[:_ERROR_CHARS] or f"exit code {found.exit_code}"
        return PiCostError(message=f"pi session lookup failed: {detail}")
    paths = [line.strip() for line in found.output.split("\n") if line.strip()]
    if not paths:
        return PiCostError(message=f"no pi session file for id {sessionId!r}")
    perFile: list[tuple[list[PiSessionCost], str | None]] = []
    for path in paths:
        try:
            ran = await backend.aexecute(f"cat {shlex.quote(path)}", timeout=timeoutS)
        except Exception as exc:
            return PiCostError(
                message=f"pi session read failed: {type(exc).__name__}: {exc}"
            )
        if ran.exit_code != 0:
            detail = ran.output.strip()[:_ERROR_CHARS] or f"exit code {ran.exit_code}"
            return PiCostError(message=f"pi session read failed: {detail}")
        parsed = _parseSessionFile(ran.output, sessionId=sessionId)
        if isinstance(parsed, PiCostError):
            continue
        perFile.append(parsed)
    if not perFile:
        return PiCostError(message=f"no pi session record for id {sessionId!r}")
    cwdMatched = [costs for costs, cwd in perFile if cwd == resolved]
    chosen = cwdMatched if cwdMatched else [costs for costs, _ in perFile]
    return [cost for costs in chosen for cost in costs]


async def getPiSessionCost(
    backend: _ExecBackend,
    *,
    sessionId: str,
    workDir: str | None = None,
    timeoutS: int = 60,
) -> PiSessionCost | PiCostError:
    """Find the session file and return its summed cost."""
    found = await findCostsOfSession(
        backend, sessionId=sessionId, workDir=workDir, timeoutS=timeoutS
    )
    if isinstance(found, PiCostError):
        return found
    return addTotalCosts(found)


__all__ = [
    "addTotalCosts",
    "findCostsOfSession",
    "getPiSessionCost",
]
