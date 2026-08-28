"""Agent service: review-agent construction.

This module owns the two review deep-agents — the entry points that
turn a :class:`ReviewAgentCtx` into a compiled
:func:`deepagents.create_deep_agent` graph — plus the pure helpers the
review pipeline shares:

- :func:`createReviewAgentCtx` — ctx factory: assembles identity +
  injected model + sandbox handle + run limits (the I/O boundary).
- :func:`createSummaryAgent` / :func:`createCommentsAgent` — the two
  per-lane agent builders. Each builds its own backend wrapper, tool
  list, and middleware stack from the ctx, then calls
  :func:`deepagents.create_deep_agent` with the lane's system prompt.
  The agents are **research-only**: they produce free-form text, never
  structured output.
- :func:`assembleUserPrompt` — the user message sent to both agents
  (pure formatting; the diff artefacts' location comes from
  :func:`app.services.agent.tools.getReviewDiffDirPath`).
- :func:`combineReviewResults` + :func:`verdictFor` — the pure merge /
  verdict rules applied after the lanes finish.

Error contract: **no function in this module raises.** Expected
failures (agent-construction errors) are returned as
:class:`AgentBuildError` values; callers discriminate with
``isinstance`` and decide at their own edge (e.g. translate into a
durable step's exception) how to handle them.

Naming convention: this package intentionally uses **camelCase**
identifiers — the same convention as :mod:`app.services.github`,
:mod:`app.services.llm`, and :mod:`app.services.sandbox`.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import cast

from deepagents import create_deep_agent
from deepagents.backends.sandbox import BaseSandbox
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.tools import BaseTool
from langchain_e2b import AsyncE2BSandbox

from app.services.agent.errors import AgentBuildError
from app.services.agent.middleware import buildAgentMiddleware
from app.utils.schema import (
    CodeCommentDraft,
    ReviewComments,
    ReviewResult,
    ReviewVerdictStr,
)
from app.services.agent.prompts import (
    PR_SUMMARY_SYSTEM_PROMPT,
    REVIEW_COMMENTS_SYSTEM_PROMPT,
)
from app.services.agent.tools import getReviewDiffDirPath, makeGetDiffTool
from app.services.agent.types import DeepAgentGraph, ReviewAgentCtx
from app.services.sandbox.errors import SandboxProviderError
from app.services.sandbox.service import getProvider
from app.services.sandbox.types import SandboxCtx
from app.utils.branded import CommitId, PRNumber, RepoId, RepoName, UserId

_DEFAULT_MODEL_CALL_RUN_LIMIT = 350
_DEFAULT_TOOL_CALL_RUN_LIMIT = 350

"""Working directory the deepagents backend runs commands from."""


def createReviewAgentCtx(
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
) -> ReviewAgentCtx:
    """Assemble a :class:`ReviewAgentCtx`.

    The chat model and sandbox handle are injected here — the ctx
    factory is the I/O boundary ("edge"). Identity is validated
    upstream (webhook receiver / workflow input), so no checks happen
    here. The result is **not serializable**: it carries live
    dependencies and never crosses a DBOS boundary; callers build it
    per run inside their steps.
    """
    return ReviewAgentCtx(
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


async def buildAgentBackend(sandboxCtx: SandboxCtx):
    """Wrap the E2B sandbox for the deepagents runtime.

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


def buildAgentTools(
    sandbox: BaseSandbox,
    prNumber: int,
    headSha: str,
    workDir: str,
) -> list[BaseTool]:
    """Return the tool list every review agent receives.

    ``get_diff`` reads the unified PR diff from the sandbox. The split
    step also writes ``overview.md`` and the per-file annotated chunks
    under ``splitted_diffs/`` next to ``file.diff``; the agents read
    those via the deepagents backend's ``read_file`` / ``ls`` tools
    (inherited separately).
    """
    return [
        makeGetDiffTool(
            sandbox=sandbox,
            workDir=workDir,
            prNumber=prNumber,
            headSha=headSha,
        )
    ]


async def buildAgent(
    ctx: ReviewAgentCtx,
    systemPrompt: str,
):
    """Run ``create_deep_agent`` for one lane; on failure return
    :class:`AgentBuildError` instead of raising.

    The backend wrapper, tool list, and middleware stack are built
    from the ctx here, so a failure at any point (backend wrapping,
    middleware construction, deep-agent assembly) folds into the
    returned error value carrying the run identity.
    """
    try:
        backend = await buildAgentBackend(ctx.sandboxCtx)
        if isinstance(backend, SandboxProviderError):
            return backend

        tools = buildAgentTools(
            sandbox=backend,
            workDir=ctx.sandboxCtx.rootPath,
            prNumber=ctx.prNumber,
            headSha=ctx.headSha,
        )

        middleware = buildAgentMiddleware(
            modelCallRunLimit=ctx.modelCallRunLimit,
            toolCallRunLimit=ctx.toolCallRunLimit,
        )

        return cast(
            DeepAgentGraph,
            create_deep_agent(
                model=ctx.model,
                system_prompt=systemPrompt,
                backend=backend,
                tools=tools,
                middleware=middleware,
            ),
        )
    except Exception as exc:
        return AgentBuildError(
            message=f"failed to build review agent: {type(exc).__name__}: {exc}",
            userId=ctx.userId,
            repoId=ctx.repoId,
            prNumber=ctx.prNumber,
            headSha=ctx.headSha,
        )


async def createSummaryAgent(ctx: ReviewAgentCtx):
    """Build the PR-summary deep-agent.

    The agent is research-only: it produces a free-form markdown
    walkthrough as its final message (no structured output). The
    structured :class:`SummaryResult` payload is produced afterwards
    by an extractor step, which re-invokes a small
    structured-output-capable model with the agent's text.

    The shared middleware stack
    (:func:`app.services.agent.middleware.buildAgentMiddleware`) wraps
    the model call with retries and caps model/tool calls per run.

    Returns:
        The compiled agent graph, or an :class:`AgentBuildError` when
        the construction fails. Never raises.
    """
    return await buildAgent(ctx, systemPrompt=PR_SUMMARY_SYSTEM_PROMPT)


async def createCommentsAgent(ctx: ReviewAgentCtx):
    """Build the comments deep-agent (all severities in one review).

    The agent is research-only: it produces a free-form findings
    report (one block per finding with exact anchors) as its final
    message — no structured output. The structured
    :class:`ReviewComments` payload is produced afterwards by an
    extractor step.

    The prompt drives a file-by-file workflow over the per-file chunks
    in ``splitted_diffs/`` (anchoring comments to gutter-visible lines
    only) and delegates the passes to the ``task`` tool's
    ``general-purpose`` subagent when the PR is large.

    Returns:
        The compiled agent graph, or an :class:`AgentBuildError` when
        the construction fails. Never raises.
    """
    return await buildAgent(ctx, systemPrompt=REVIEW_COMMENTS_SYSTEM_PROMPT)


def createUserPrompt(ctx: ReviewAgentCtx) -> str:
    """Build the user message sent to each of the two review agents.

    Pure formatting — no I/O, no LLM. The diff is not inlined; the
    message carries the concrete Diff dir path (with ``overview.md``,
    ``splitted_diffs/``, and ``file.diff``) so the agents never have
    to discover it.
    """
    diff_dir = getReviewDiffDirPath(
        workDir=ctx.sandboxCtx.rootPath,
        prNumber=ctx.prNumber,
        headSha=ctx.headSha,
    )

    return (
        f"Repo: {ctx.repoName} (id={ctx.repoId})\n"
        f"User: {ctx.userId}\n"
        f"PR number: {ctx.prNumber}\n"
        f"Head SHA: {ctx.headSha}\n"
        f"Diff dir: {diff_dir}/\n"
        f"\n"
        f"The PR diff artefacts live in the Diff dir above: read "
        f"overview.md first, then the per-file chunks under "
        f"splitted_diffs/ (file.diff is the raw unified diff; the "
        f"get_diff(limit:int , offset:int) tool reads it).\n"
    )


_SEVERITY_RANK: dict[str, int] = {
    "P1_CRITICAL": 0,
    "P2_WARNING": 1,
    "P3_NITPICK": 2,
}


def verdictFor(comments: Sequence[CodeCommentDraft]) -> ReviewVerdictStr:
    """Return the review verdict implied by ``comments``.

    Pure rule:

    - any ``P1_CRITICAL`` → ``REQUEST_CHANGES``
    - else any ``P2_WARNING`` / ``P3_NITPICK`` → ``COMMENT``
    - else → ``APPROVE``
    """
    for draft in comments:
        if draft.severity == "P1_CRITICAL":
            return "REQUEST_CHANGES"
    for draft in comments:
        if draft.severity in ("P2_WARNING", "P3_NITPICK"):
            return "COMMENT"
    return "APPROVE"


def combineReviewResults(
    *,
    summaryMarkdown: str,
    comments: ReviewComments,
) -> ReviewResult:
    """Merge the two agent outputs into one :class:`ReviewResult`.

    Comments are sorted in severity order (P1 → P2 → P3) so the
    GitHub review renders with the most important findings first. The
    summary is the summarizer's markdown verbatim. The verdict is
    computed from the merged comments by :func:`verdictFor`.

    No dedup. The single comments agent is asked not to repeat
    itself; adding a dedup pass here would need an LLM or fuzzy rules
    and isn't worth the complexity for the rare case.
    """
    return ReviewResult(
        comments=sorted(
            comments.List,
            key=lambda draft: _SEVERITY_RANK.get(draft.severity, len(_SEVERITY_RANK)),
        ),
        summary=summaryMarkdown,
        verdict=verdictFor(comments.List),
    )


__all__ = [
    "createUserPrompt",
    "combineReviewResults",
    "createCommentsAgent",
    "createReviewAgentCtx",
    "createSummaryAgent",
    "verdictFor",
]
