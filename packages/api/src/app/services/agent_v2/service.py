"""Agent-v2 service: planning-agent + per-file review-agent construction.

This module owns the two v2 deep-agents — the entry points that turn
an :class:`AgentV2Ctx` into a compiled
:func:`deepagents.create_deep_agent` graph — plus the pure prompt
helpers the v2 pipeline shares:

- :func:`createAgentV2Ctx` — ctx factory: assembles identity +
  injected model + sandbox handle + run limits (the I/O boundary).
- :func:`createPlanningAgent` / :func:`createFileReviewAgent` — the
  two agent builders. Each builds its own backend wrapper, empty tool
  list, and no-subagent middleware stack from the ctx, then calls
  :func:`deepagents.create_deep_agent` with ``subagents=[]`` and the
  lane's (currently placeholder) system prompt. The agents are
  **research-only**: they produce free-form text, never structured
  output.
- :func:`createPlanningUserPrompt` / :func:`createFileReviewUserPrompt`
  — the user messages (pure formatting; the diff artefacts' location
  comes from :func:`app.services.agent.tools.getReviewDiffDirPath`,
  reused so the path can never drift from the v1 pipeline).
- :func:`chunkFileForPath` — the on-disk dotted chunk name for a real
  path (mirrors the split script's ``name.replace("/", ".")`` rule).

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
identifiers — the same convention as :mod:`app.services.agent`,
:mod:`app.services.github`, :mod:`app.services.llm`, and
:mod:`app.services.sandbox`.
"""

from __future__ import annotations

from typing import cast

from deepagents import create_deep_agent
from deepagents.backends.sandbox import BaseSandbox
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.tools import BaseTool

from app.services.agent.tools import getReviewDiffDirPath
from app.services.agent_v2._middleware import buildNoSubMiddleware
from app.services.agent_v2.errors import AgentV2BuildError
from app.services.agent_v2.prompts import (
    FILE_REVIEW_SYSTEM_PROMPT,
    PLANNING_SYSTEM_PROMPT,
)
from app.services.agent_v2.types import (
    AgentV2Ctx,
    DeepAgentGraph,
    FileReviewJob,
)
from app.services.sandbox.errors import SandboxProviderError
from app.services.sandbox.service import getProvider
from app.services.sandbox.types import SandboxCtx
from app.utils.branded import CommitId, PRNumber, RepoId, RepoName, UserId
from app.utils.util import repo_path

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
        modelCallRunLimit=modelCallRunLimit,
        toolCallRunLimit=toolCallRunLimit,
    )


async def buildNoSubBackend(sandboxCtx: SandboxCtx):
    """Wrap the sandbox for the deepagents runtime.

    Each agent gets its own backend wrapper over the same underlying
    sandbox; the connection is held by the caller and reused by every
    concurrent ``ainvoke``. Mirrors
    :func:`app.services.agent.service.buildAgentBackend` so the v2
    backend behaves identically.
    """
    ProviderCls = getProvider(sandboxCtx.providerId)
    provider = ProviderCls(ctx=sandboxCtx)
    sandbox = await provider.create()

    if isinstance(sandbox, SandboxProviderError):
        return sandbox

    return sandbox


def chunkFileForPath(file: str) -> str:
    """Return the on-disk chunk file name for a real repo path.

    Mirrors the split script's flattening rule
    (``result.name.replace("/", ".") + ".md"``); used only to name the
    chunk in prompts. The list-chunks step keys the inventory off the
    ``### <real path>`` header, never off this name.
    """
    return file.replace("/", ".") + ".md"


async def buildNoSubAgent(
    ctx: AgentV2Ctx,
    systemPrompt: str,
):
    """Run ``create_deep_agent`` with delegation disabled.

    The backend wrapper, empty tool list, and no-subagent middleware
    stack are built from the ctx here, so a failure at any point
    (backend wrapping, unknown provider, deep-agent assembly) folds
    into the returned error value carrying the run identity.
    """
    try:
        backend = await buildNoSubBackend(ctx.sandboxCtx)
        if isinstance(backend, SandboxProviderError):
            return backend

        tools: list[BaseTool] = []

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
    with free-form planning text. The structured
    :class:`PlannerContext` payload is produced afterwards by the
    plan-extractor step.

    Returns:
        The compiled agent graph, or an :class:`AgentV2BuildError` /
        :class:`SandboxProviderError` when the construction fails.
        Never raises.
    """
    return await buildNoSubAgent(ctx, systemPrompt=PLANNING_SYSTEM_PROMPT)


async def createFileReviewAgent(ctx: AgentV2Ctx, *, file: str):
    """Build one per-file review deep-agent (no subagents, no delegation).

    Research-only: it reviews its single chunk (plus the planner
    context slice carried in its user prompt) and ends with a findings
    report or ``NO_FINDINGS``. The structured
    :class:`ReviewComments` payload is produced afterwards by the
    shared comments-extractor step over the merged reports.

    ``file`` is informational (surfaces in errors); the scope lives in
    the user prompt built by :func:`createFileReviewUserPrompt`.

    Returns:
        The compiled agent graph, or an :class:`AgentV2BuildError` /
        :class:`SandboxProviderError` when the construction fails.
        Never raises.
    """
    _ = file
    return await buildNoSubAgent(ctx, systemPrompt=FILE_REVIEW_SYSTEM_PROMPT)


def createPlanningUserPrompt(ctx: AgentV2Ctx, *, actualFiles: list[str]) -> str:
    """Build the user message for the planning agent.

    Pure formatting — no I/O, no LLM. Carries the concrete diff-dir
    path plus the host-side chunk inventory (so the planner spends its
    budget exploring, not discovering what changed) and the repo root.
    The diff itself is never inlined.
    """
    diff_dir = getReviewDiffDirPath(
        workDir=ctx.sandboxCtx.rootPath,
        prNumber=ctx.prNumber,
        headSha=ctx.headSha,
    )
    files_block = "\n".join(f"- {path}" for path in actualFiles) or "- (no chunks)"

    return (
        f"Repo: {ctx.repoName} (id={ctx.repoId})\n"
        f"User: {ctx.userId}\n"
        f"PR number: {ctx.prNumber}\n"
        f"Head SHA: {ctx.headSha}\n"
        f"Diff dir: {diff_dir}/\n"
        f"Repo root: {repo_path(ctx.repoName)}\n"
        f"\n"
        f"Changed files with reviewable chunks ({len(actualFiles)}):\n"
        f"{files_block}\n"
        f"\n"
        f"The PR diff artefacts live in the Diff dir above. Use "
        f"strictly overview.md and the per-file chunks under "
        f"splitted_diffs/ for diff context — nothing else.\n"
    )


def createFileReviewUserPrompt(
    ctx: AgentV2Ctx,
    *,
    job: FileReviewJob,
    sharedConcerns: str,
) -> str:
    """Build the user message for one per-file review agent.

    Pure formatting — no I/O, no LLM. Scopes the agent to its single
    chunk (named explicitly) and attaches its planner-context slice
    plus the shared concerns. Other files' chunks are never named, so
    the agent has no reason to open them.
    """
    diff_dir = getReviewDiffDirPath(
        workDir=ctx.sandboxCtx.rootPath,
        prNumber=ctx.prNumber,
        headSha=ctx.headSha,
    )
    focus_block = ", ".join(job.focus) if job.focus else "(general review)"
    symbols_block = ", ".join(job.relevantSymbols) if job.relevantSymbols else "(none)"
    context_block = job.crossFileContext or "(no planner context for this file)"
    concerns_block = sharedConcerns or "(none)"

    return (
        f"Repo: {ctx.repoName} (id={ctx.repoId})\n"
        f"User: {ctx.userId}\n"
        f"PR number: {ctx.prNumber}\n"
        f"Head SHA: {ctx.headSha}\n"
        f"Diff dir: {diff_dir}/\n"
        f"Repo root: {repo_path(ctx.repoName)}\n"
        f"\n"
        f"Review exactly this file's chunk and nothing else:\n"
        f"- file: {job.file}\n"
        f"- chunk: {diff_dir}/splitted_diffs/{chunkFileForPath(job.file)}\n"
        f"- suggested focus: {focus_block}\n"
        f"- relevant symbols: {symbols_block}\n"
        f"\n"
        f"Planner cross-file context for this file:\n"
        f"{context_block}\n"
        f"\n"
        f"Shared concerns for this PR:\n"
        f"{concerns_block}\n"
        f"\n"
        f"Anchor every finding ONLY to a gutter-visible line in this "
        f"file's chunk. If the file is clean, answer exactly NO_FINDINGS.\n"
    )


__all__ = [
    "buildNoSubAgent",
    "buildNoSubBackend",
    "chunkFileForPath",
    "createAgentV2Ctx",
    "createFileReviewAgent",
    "createFileReviewUserPrompt",
    "createPlanningAgent",
    "createPlanningUserPrompt",
]
