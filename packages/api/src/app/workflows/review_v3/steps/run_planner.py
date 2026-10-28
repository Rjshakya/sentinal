"""Run the planner pi agent; return the validated plan file path.

One ``pi --print`` run (session ``…-plan``) whose prompt points at
``./{repo}/`` + ``./{head_sha}/diff/`` and orders the agent to write
``./{head_sha}/plan.jsonl``. The host validates the file exists, is
non-empty, and every line parses as JSON — schema stays owned by the
prompt (next turn) — then returns the sandbox-absolute path. The
reviewer step reads the plan from that path; the plan cost stays
attributable to the ``…-plan`` session id.
"""

from __future__ import annotations

import json
import shlex

from app.services.llm_config.types import LLMConfigCtx
from app.services.pi_harness.harness import PiAgentHarness, modelFromCtx, phaseSessionId
from app.services.sandbox.errors import SandboxProviderError
from app.services.sandbox.service import getProvider
from app.services.sandbox.types import BaseSandbox, SandboxCtx
from app.utils.branded import CommitId, PRNumber, RepoName
from app.utils.sandbox_fs import getPlanFile
from app.workflows.review_v3.errors import PlannerError
from app.workflows.review_v3.types import PlanFilePath

_RUN_TIMEOUT_S = 600
_READ_TIMEOUT_S = 60
_ERROR_CHARS = 500


async def runPlanner(
    *,
    sandboxCtx: SandboxCtx,
    llm: LLMConfigCtx,
    prNumber: PRNumber,
    headSha: CommitId,
    repoName: RepoName,
    prompt: str,
    systemPrompts: list[str] | None = None,
    runTimeoutS: int = _RUN_TIMEOUT_S,
) -> PlanFilePath | PlannerError:
    """Run the planner agent and return the validated plan file path."""
    if not prompt.strip():
        raise ValueError("prompt must be non-empty")
    try:
        provider = getProvider(sandboxCtx.providerId)
    except Exception as exc:
        return PlannerError(
            message=f"unknown sandbox provider: {type(exc).__name__}: {exc}",
            retryable=True,
        )
    try:
        made = await provider(ctx=sandboxCtx).create()
    except Exception as exc:
        return PlannerError(
            message=f"sandbox reconnect raised {type(exc).__name__}: {exc}",
            retryable=True,
        )
    if isinstance(made, SandboxProviderError):
        return PlannerError(
            message=f"sandbox reconnect failed: {made.message}", retryable=True
        )
    backend: BaseSandbox = made

    sessionId = phaseSessionId(
        prNumber=int(prNumber), headSha=str(headSha), phase="plan"
    )
    harness = PiAgentHarness(sessionId=sessionId, model=modelFromCtx(llm))
    for systemPrompt in systemPrompts or []:
        harness.appendSystemPrompt(systemPrompt)
    try:
        result = await harness.run(prompt, backend, timeoutS=runTimeoutS)
    except Exception as exc:
        return PlannerError(
            message=f"planner run raised {type(exc).__name__}: {exc}",
            retryable=True,
        )
    if not result.ok:
        return PlannerError(
            message=f"planner run failed: {result.error or 'unknown error'}"
        )

    _ = repoName
    planFile = getPlanFile(str(headSha))
    try:
        read = await backend.aexecute(
            f"cat {shlex.quote(planFile)}", timeout=_READ_TIMEOUT_S
        )
    except Exception as exc:
        return PlannerError(
            message=f"plan read raised {type(exc).__name__}: {exc}", retryable=True
        )
    if read.exit_code != 0:
        return PlannerError(
            message=f"plan file missing: {read.output.strip()[-_ERROR_CHARS:]}"
        )
    lines = [line for line in read.output.split("\n") if line.strip()]
    if not lines:
        return PlannerError(message="plan file is empty")
    for line in lines:
        try:
            json.loads(line)
        except Exception as exc:
            return PlannerError(
                message=f"plan file has a non-JSON line: {type(exc).__name__}: {exc}"
            )
    return PlanFilePath(planFile)


__all__ = ["runPlanner"]
