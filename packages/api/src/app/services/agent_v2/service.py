"""Agent-v2 service: planning-agent + per-file review-agent construction.

This module owns the two v2 deep-agents — the entry points that turn
an :class:`AgentV2Ctx` into a compiled
:func:`deepagents.create_deep_agent` graph:

- :func:`createAgentV2Ctx` — ctx factory: assembles identity +
  injected model + sandbox handle + run limits (the I/O boundary).
- :func:`createPlanningAgent` / :func:`createFileReviewAgent` — the
  two agent builders. Each builds its own backend wrapper, empty tool
  list, and no-subagent middleware stack from the ctx, then calls
  :func:`deepagents.create_deep_agent` with ``subagents=[]`` and the
  lane's system prompt built by
  :func:`app.services.agent_v2.prompts.createPlanningSystemPrompt` /
  :func:`app.services.agent_v2.prompts.createFileReviewSystemPrompt`
  from the ctx's narrow scalars. The agents are **research-only**:
  they produce free-form text, never structured output.

Prompt wording lives in :mod:`app.services.agent_v2.prompts` (one
function per prompt); this module owns no prompt text and no
middleware assembly (imports from :mod:`._middleware`). It does own
the ``submit_plan`` tool mechanics (:func:`buildSubmitPlanTool`,
closed over the ctx) and the host-owned plan path
(:func:`planFilePath`).

No-delegation guarantee (two layers, both per-agent — no
process-global profile registration, so the v1 pipeline sharing the
process is unaffected):

1. ``subagents=[]`` — documents intent; note ``create_deep_agent``
   still auto-adds its default ``general-purpose`` subagent spec.
2. :class:`app.services.agent_v2._middleware.NoDelegationMiddleware`
   — strips the ``task`` tool from every model request, so the model
   can never delegate through it.

Error contract: **no function in this module raises.** Expected
failures (agent-construction errors) are returned as
:class:`AgentV2BuildError` values; callers discriminate with
``isinstance`` and decide at their own edge (e.g. translate into a
durable step's exception) how to handle them.

Naming convention: this package intentionally uses **camelCase**
identifiers — the same convention as :mod:`app.services.github`,
:mod:`app.services.llm`, and :mod:`app.services.sandbox`.
"""

from __future__ import annotations

import shlex
from collections.abc import Sequence
from typing import Any, Literal, Protocol, cast

from deepagents import create_deep_agent
from deepagents.backends.protocol import ExecuteResponse, FileUploadResponse
from deepagents.backends.sandbox import BaseSandbox
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.tools import BaseTool
from langchain_core.tools import tool as langchain_tool
from pydantic import BaseModel, Field, ValidationError

from app.services.agent_v2._middleware import buildNoSubMiddleware
from app.services.agent_v2.errors import AgentV2BuildError
from app.services.agent_v2.prompts import (
    SEARCH_CODEGRAPH_TOOL_DESCRIPTION,
    SUBMIT_PLAN_TOOL_DESCRIPTION,
    createFileReviewSystemPrompt,
    createPlanningSystemPrompt,
)
from app.services.agent_v2.types import (
    AgentV2Ctx,
    DeepAgentGraph,
    PlannerContext,
)
from app.services.sandbox.errors import SandboxProviderError
from app.services.sandbox.service import getProvider
from app.services.sandbox.types import SandboxCtx
from app.utils.branded import CommitId, PRNumber, RepoId, RepoName, UserId
from app.utils.util import graph_db_path

_DEFAULT_MODEL_CALL_RUN_LIMIT = 120
_DEFAULT_TOOL_CALL_RUN_LIMIT = 120


def createAgentV2Ctx(
    *,
    userId: UserId,
    repoId: RepoId,
    repoName: RepoName,
    prNumber: PRNumber,
    headSha: CommitId,
    model: BaseChatModel,
    sandboxCtx: SandboxCtx,
    systemPrompt: str,
    modelCallRunLimit: int = _DEFAULT_MODEL_CALL_RUN_LIMIT,
    toolCallRunLimit: int = _DEFAULT_TOOL_CALL_RUN_LIMIT,
) -> AgentV2Ctx:
    """Assemble an :class:`AgentV2Ctx`.

    The chat model and sandbox handle are injected here — the ctx
    factory is the I/O boundary ("edge"). Identity is validated
    upstream (webhook receiver / workflow input), so no checks happen
    here. The result is **not serializable**: it carries live
    dependencies and never crosses a DBOS boundary; callers build it
    per run inside their steps.
    """
    return AgentV2Ctx(
        userId=userId,
        repoId=repoId,
        repoName=repoName,
        prNumber=prNumber,
        headSha=headSha,
        model=model,
        sandboxCtx=sandboxCtx,
        systemPrompt=systemPrompt,
        modelCallRunLimit=modelCallRunLimit,
        toolCallRunLimit=toolCallRunLimit,
    )


async def buildNoSubBackend(sandboxCtx: SandboxCtx):
    """Wrap the sandbox for the deepagents runtime.

    Each agent gets its own backend wrapper over the same underlying
    sandbox; the connection is held by the caller and reused by every
    concurrent ``ainvoke``.
    """
    ProviderCls = getProvider(sandboxCtx.providerId)
    provider = ProviderCls(ctx=sandboxCtx)
    sandbox = await provider.create()

    if isinstance(sandbox, SandboxProviderError):
        return sandbox

    return sandbox


class _PlanWriter(Protocol):
    """The backend surface the submit-plan tool needs (upload = overwrite)."""

    async def aupload_files(
        self, files: list[tuple[str, bytes]]
    ) -> list[FileUploadResponse]: ...


def planFilePath(workDir: str) -> str:
    """Return the host-owned plan location: ``{workDir}/plan.json``.

    Pure helper — the submit tool (write) and ``getPlanStep`` (read)
    recompute the identical path, so it can never drift. Prompts never
    name this path; the agent reaches it only through ``submit_plan``.
    """
    return f"{workDir}/plan.json"


def buildSubmitPlanTool(*, ctx: AgentV2Ctx, planPath: str) -> BaseTool:
    """Build the ``submit_plan`` tool bound to this run's sandbox + path.

    The tool closes over the ctx (not agent state — state is
    checkpointed, and live handles must never be serialized there):
    on each call it reconnects, validates the submission into a
    :class:`PlannerContext`, and overwrites ``plan.json`` so a
    duplicate submission simply wins instead of failing the run.
    Failures are returned as error strings (the agent can retry
    within its budget), never raised — matching the service's
    error contract.
    """

    async def _submitPlan(**kwargs: Any) -> str:
        try:
            plan = PlannerContext(**kwargs)
        except ValidationError as exc:
            return f"plan rejected (schema): {exc.errors(include_url=False)}"

        try:
            payload = plan.model_dump_json().encode("utf-8")
        except Exception as exc:
            return f"plan rejected (encode): {type(exc).__name__}: {exc}"

        backend = await buildNoSubBackend(ctx.sandboxCtx)
        if isinstance(backend, SandboxProviderError):
            return f"plan not saved (transient): {backend.message}"
        try:
            uploads = await cast(_PlanWriter, backend).aupload_files(
                [(planPath, payload)]
            )
        except Exception as exc:
            return f"plan not saved (transient): {type(exc).__name__}: {exc}"
        failed = next((u.error for u in uploads if u.error is not None), None)
        if failed is not None:
            return f"plan not saved (transient): {failed}"
        return f"plan saved: {len(plan.fileContexts)} file(s)"

    return langchain_tool(
        "submit_plan",
        description=SUBMIT_PLAN_TOOL_DESCRIPTION,
        args_schema=PlannerContext,
    )(_submitPlan)


CodeGraphVerb = Literal[
    "overview",
    "files",
    "search",
    "node",
    "callees",
    "callers",
    "children",
    "imports",
]
"""Verbs the ``search_codegraph`` tool exposes (the full query ladder)."""

_DRILL_VERBS: tuple[str, ...] = ("node", "callees", "callers", "children")
"""Verbs resolving one node by ``--id`` or exact ``--name``."""

_SEARCH_TIMEOUT_S: int = 120
"""Upper bound on one in-sandbox ``codegraph query`` (local reads)."""


class CodeGraphSearchArgs(BaseModel):
    """Argument schema for the ``search_codegraph`` tool."""

    verb: CodeGraphVerb = Field(
        description="which graph query to run (exactly one per call)"
    )
    name: str | None = Field(
        default=None,
        description="def-name fragment (search) or exact name (drills)",
    )
    file: str | None = Field(
        default=None,
        description="narrow to one repo-relative file path",
    )
    node_id: str | None = Field(
        default=None,
        description="exact node id for drills (preferred over name)",
    )
    limit: int = Field(default=20, description="max search hits")


class _CommandRunner(Protocol):
    """The backend surface the search tool needs (one command run)."""

    async def aexecute(
        self,
        command: str,
        *,
        timeout: int | None = None,
    ) -> ExecuteResponse: ...


def buildCodeGraphQueryCommand(
    *,
    verb: str,
    name: str | None,
    file: str | None,
    node_id: str | None,
    limit: int,
    db_path: str | None = None,
) -> str | None:
    """Build the in-sandbox ``codegraph query`` argv, or None.

    Pure / testable. Returns None when the args cannot satisfy the
    verb (``search`` without a fragment, a drill without id or name,
    ``imports`` without file or id) so the tool answers without
    spending a sandbox round-trip on a guaranteed CLI error. The
    database path defaults to the fixed run constant both the index
    step and this tool recompute; pass ``db_path`` to target another
    database (e.g. the CLI default in live tests).
    """
    db: str = db_path or graph_db_path()
    parts: list[str] = ["codegraph", "query", "--db", db, "--json", verb]
    if verb == "search":
        if not name:
            return None
        parts += ["--name", name]
        if file:
            parts += ["--file", file]
        parts += ["--limit", str(limit)]
    elif verb in _DRILL_VERBS:
        if node_id:
            parts += ["--id", node_id]
        elif name:
            parts += ["--name", name]
            if file:
                parts += ["--file", file]
        else:
            return None
    elif verb == "imports":
        if node_id:
            parts += ["--id", node_id]
        elif file:
            parts += ["--file", file]
        else:
            return None
    return " ".join(shlex.quote(part) for part in parts)


def buildCodeGraphSearchTool(*, ctx: AgentV2Ctx) -> BaseTool:
    """Build the ``search_codegraph`` tool bound to this run's sandbox.

    The tool closes over the ctx (not agent state): on each call it
    reconnects, runs the query argv, and returns the JSON envelope
    stdout for the model to chain on. Failures are returned as error
    strings (the agent reports and continues with grep/reads), never
    raised — matching the service's error contract.
    """

    async def _searchCodeGraph(
        verb: CodeGraphVerb,
        name: str | None = None,
        file: str | None = None,
        node_id: str | None = None,
        limit: int = 20,
    ) -> str:
        command: str | None = buildCodeGraphQueryCommand(
            verb=verb,
            name=name,
            file=file,
            node_id=node_id,
            limit=limit,
            db_path=graph_db_path(),
        )
        if command is None:
            return (
                "search rejected (args): this verb needs a name fragment "
                "(search), an id or name (drills), or a file/id (imports)"
            )
        backend = await buildNoSubBackend(ctx.sandboxCtx)
        if isinstance(backend, SandboxProviderError):
            return f"search unavailable (transient): {backend.message}"
        try:
            result: ExecuteResponse = await cast(
                _CommandRunner, backend
            ).aexecute(command, timeout=_SEARCH_TIMEOUT_S)
        except Exception as exc:
            return f"search unavailable (transient): {type(exc).__name__}: {exc}"
        if result.exit_code != 0:
            tail: str = (result.output or "").strip()[:500]
            return f"search unavailable (exit {result.exit_code}): {tail}"
        return result.output.strip() or "search returned no output"

    return langchain_tool(
        "search_codegraph",
        description=SEARCH_CODEGRAPH_TOOL_DESCRIPTION,
        args_schema=CodeGraphSearchArgs,
    )(_searchCodeGraph)


async def buildNoSubAgent(
    ctx: AgentV2Ctx,
    systemPrompt: str,
    tools: Sequence[BaseTool] = (),
):
    """Run ``create_deep_agent`` with delegation disabled.

    The backend wrapper, tool list, and no-subagent middleware stack
    are built from the ctx here, so a failure at any point (backend
    wrapping, unknown provider, deep-agent assembly) folds into the
    returned error value carrying the run identity.
    """
    try:
        backend = await buildNoSubBackend(ctx.sandboxCtx)
        if isinstance(backend, SandboxProviderError):
            return backend

        middlewares = buildNoSubMiddleware(
            modelCallRunLimit=ctx.modelCallRunLimit,
            toolCallRunLimit=ctx.toolCallRunLimit,
        )

        return cast(
            DeepAgentGraph,
            create_deep_agent(
                model=ctx.model,
                system_prompt=systemPrompt,
                backend=cast(BaseSandbox, backend),
                tools=tools,
                subagents=[],
                middleware=middlewares,
            ),
        )
    except Exception as exc:
        return AgentV2BuildError(
            message=f"failed to build v2 review agent: {type(exc).__name__}: {exc}",
            userId=ctx.userId,
            repoId=ctx.repoId,
            prNumber=ctx.prNumber,
            headSha=ctx.headSha,
        )


async def createPlanningAgent(ctx: AgentV2Ctx):
    """Build the planning deep-agent (no subagents, no delegation).

    Research-only: it explores the repo + the split chunks and ends
    by calling the ``submit_plan`` tool, which persists the
    :class:`PlannerContext` to the run's ``plan.json`` for
    ``getPlanStep`` to read back. The tool is built here (closed over
    the ctx, never over agent state) and is the agent's only custom
    tool alongside the backend built-ins.

    Returns:
        The compiled agent graph, or an :class:`AgentV2BuildError` /
        :class:`SandboxProviderError` when the construction fails.
        Never raises.
    """
    return await buildNoSubAgent(
        ctx,
        systemPrompt=ctx.systemPrompt,
        tools=[
            buildSubmitPlanTool(
                ctx=ctx,
                planPath=planFilePath(ctx.sandboxCtx.rootPath),
            ),
            buildCodeGraphSearchTool(ctx=ctx),
        ],
    )


async def createFileReviewAgent(ctx: AgentV2Ctx, *, filePath: str):
    """Build one per-file review deep-agent (no subagents, no delegation).

    Research-only: it reviews its single chunk (plus the planner
    context slice carried in its user prompt) and ends with a findings
    report or ``NO_FINDINGS``. The structured
    :class:`ReviewComments` payload is produced afterwards by the
    shared comments-extractor step over the merged reports.

    ``filePath`` is informational (surfaces in errors); the scope lives
    in the user prompt built by :func:`createFileReviewUserPrompt`.

    Returns:
        The compiled agent graph, or an :class:`AgentV2BuildError` /
        :class:`SandboxProviderError` when the construction fails.
        Never raises.
    """
    _ = filePath
    return await buildNoSubAgent(
        ctx,
        systemPrompt=createFileReviewSystemPrompt(
            repoName=ctx.repoName,
            userId=ctx.userId,
            modelCallRunLimit=ctx.modelCallRunLimit,
            toolCallRunLimit=ctx.toolCallRunLimit,
        ),
        tools=[
            buildCodeGraphSearchTool(ctx=ctx),
        ],
    )


__all__ = [
    "CodeGraphSearchArgs",
    "CodeGraphVerb",
    "buildCodeGraphQueryCommand",
    "buildCodeGraphSearchTool",
    "buildNoSubAgent",
    "buildNoSubBackend",
    "buildSubmitPlanTool",
    "createAgentV2Ctx",
    "createFileReviewAgent",
    "createPlanningAgent",
    "planFilePath",
]
