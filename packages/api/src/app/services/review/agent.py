"""Review deep-agent factory.

All review-specific agent composition lives here: prompt assembly,
specialist subagent wiring, and graph construction. The module is pure
— no I/O, no session, no clock.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence

from deepagents import SubAgent, create_deep_agent
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.tools import BaseTool
from langchain_e2b import AsyncE2BSandbox

from app.core.llm import LLMProviderStr, build_chat_model
from app.core.sandbox import BaseSandbox
from app.core.sandbox.e2b import E2BSandbox
from app.services.agent.models import (
    CorrectnessComments,
    ReviewResult,
    SecurityComments,
    StyleComments,
)
from app.services.agent.prompts import (
    CORRECTNESS_SYSTEM_PROMPT,
    PR_SUMMARY_SYSTEM_PROMPT,
    REVIEW_ORCHESTRATOR_SYSTEM_PROMPT,
    SECURITY_SYSTEM_PROMPT,
    STYLE_SYSTEM_PROMPT,
)
from app.services.review.hunk_map import HunkMap
from app.services.review.tools import (
    make_get_diff_tool,
    make_verify_comment_line_tool,
)
from app.services.review.types import DeepAgentGraph

log = logging.getLogger(__name__)


def assemble_orchestrator_system_prompt() -> str:
    """Return the system prompt for the orchestrator deep-agent.

    The orchestrator is the single ``create_deep_agent`` instance; the
    three specialists (security / correctness / style) are wired in as
    :class:`SubAgent` children via :func:`assemble_review_subagents`.
    """
    return REVIEW_ORCHESTRATOR_SYSTEM_PROMPT


def assemble_review_subagents(
    *,
    sandbox: BaseSandbox,
    pr_number: int,
    head_sha: str,
    hunk_map: HunkMap,
) -> list[SubAgent]:
    """Return the four specialist subagents the orchestrator delegates to.

    Each subagent gets a unique ``name`` (used as the dispatch key in
    the orchestrator's ``task()`` tool), a one-line ``description`` the
    orchestrator uses to decide which subagent to call, and the
    specialist's own system prompt. Tools are intentionally not set:
    the deepagents runtime inherits the parent's backend tools (the
    E2B sandbox's ``read`` / ``write`` / ``execute`` / etc.), so each
    specialist can verify a suspicion against the repo when needed.

    All four subagents receive ``get_diff_tool`` (read the unified diff)
    and ``verify_comment_line_tool`` (validate a ``(file, line, side)``
    anchor against the parsed :data:`HunkMap`). The summarizer does
    not emit comments but receives the tools for consistency.

    The first subagent, ``summarizer``, is the PR-summary writer. The
    orchestrator calls it first, takes its markdown output verbatim,
    and embeds it as ``ReviewResult.summary`` (which is then persisted
    as the PR's review summary). The other three are the existing
    severity-bucketed reviewers and only emit findings, not prose.
    """

    get_diff_tool = make_get_diff_tool(
        sandbox=sandbox,
        pr_number=pr_number,
        head_sha=head_sha,
    )
    verify_comment_line_tool = make_verify_comment_line_tool(hunk_map=hunk_map)
    subagent_tools = [get_diff_tool, verify_comment_line_tool]

    return [
        SubAgent(
            name="summarizer",
            description=(
                "PR summary writer. Emits a grounded markdown bullet "
                "list of what the PR does (one-line title + bullets "
                "with file:line references). Call this FIRST; its "
                "output is embedded verbatim as ReviewResult.summary "
                "and persisted as the PR's review summary. Does not "
                "emit findings, bugs, or verdicts."
            ),
            system_prompt=PR_SUMMARY_SYSTEM_PROMPT,
            tools=list(subagent_tools),
        ),
        SubAgent(
            name="security",
            description=(
                "Security reviewer. Emits only P1_CRITICAL findings. "
                "Delegate to it whenever the orchestrator suspects an "
                "injection, secrets leak, auth bypass, or other "
                "security-class bug."
            ),
            system_prompt=SECURITY_SYSTEM_PROMPT,
            response_format=SecurityComments,
            tools=list(subagent_tools),
        ),
        SubAgent(
            name="correctness",
            description=(
                "Correctness reviewer. Emits only P2_WARNING findings. "
                "Delegate to it for off-by-one, missing error handling, "
                "race conditions, API misuse, and similar logic bugs."
            ),
            system_prompt=CORRECTNESS_SYSTEM_PROMPT,
            response_format=CorrectnessComments,
            tools=list(subagent_tools),
        ),
        SubAgent(
            name="style",
            description=(
                "Style reviewer. Emits only P3_NITPICK findings. "
                "Delegate to it for misleading names, dead code, "
                "stale comments, and other lintable cleanups."
            ),
            system_prompt=STYLE_SYSTEM_PROMPT,
            response_format=StyleComments,
            tools=list(subagent_tools),
        ),
    ]


def assemble_user_prompt(
    *,
    repo_name: str,
    repo_id: str,
    user_id: str,
    pr_number: int,
) -> str:
    """Build the user message sent to the review deep-agent.

    Pure formatting — no I/O, no LLM. The diff is no longer inlined;
    the agent calls the ``get_diff`` tool to read it from the sandbox.
    """
    return (
        f"Repo: {repo_name} (id={repo_id})\n"
        f"User: {user_id}\n"
        f"PR number: {pr_number}\n"
        f"\n"
        f"Call the `get_diff()` tool to read the PR diff before reviewing.\n"
    )


def get_review_agent(
    *,
    system_prompt: str,
    subagents: Sequence[SubAgent],
    backend: AsyncE2BSandbox,
    model: BaseChatModel,
    tools: Sequence[BaseTool | Callable[..., object]] = (),
) -> DeepAgentGraph:
    """Compose the review deep-agent graph.

    Pure factory — no I/O, no session. The caller owns the connected
    ``backend`` (an :class:`AsyncE2BSandbox` wrapping the E2B handle)
    and the ``model`` (a langchain chat model). The returned graph is
    invoked once per review by the orchestrator.
    """
    log.info(
        "building review deep agent: model=%s subagents=%d",
        getattr(model, "model_name", "<unknown>"),
        len(subagents),
    )
    return create_deep_agent(
        model=model,
        system_prompt=system_prompt,
        subagents=list(subagents),
        backend=backend,
        response_format=ReviewResult,
        tools=list(tools),
    )


def build_review_agent(
    *,
    sandbox: E2BSandbox,
    pr_number: int,
    head_sha: str,
    provider: LLMProviderStr,
    llm_baseurl: str | None,
    llm_api_key: str,
    llm_model: str,
    hunk_map: HunkMap,
) -> DeepAgentGraph:
    """High-level convenience factory used by the orchestrator.

    Builds the chat model, wraps the sandbox backend, and composes the
    review deep-agent with its four specialist subagents.

    ``hunk_map`` is the parsed diff structure from
    :func:`app.services.review.hunk_map.parse_hunk_map`. It is bound
    into the ``verify_comment_line`` tool so the subagents can
    self-validate ``(file, line, side)`` anchors before emitting
    :class:`CodeCommentDraft` entries.
    """
    model = build_chat_model(
        provider=provider,
        base_url=llm_baseurl,
        api_key=llm_api_key,
        model=llm_model,
        headers={"cf-aig-gateway-id": "sentinal-ai-gateway"},
    )
    backend = AsyncE2BSandbox(sandbox=sandbox.sandbox)
    get_diff_tool = make_get_diff_tool(sandbox, pr_number, head_sha)
    verify_comment_line_tool = make_verify_comment_line_tool(hunk_map=hunk_map)

    return get_review_agent(
        system_prompt=assemble_orchestrator_system_prompt(),
        subagents=assemble_review_subagents(
            sandbox=sandbox,
            pr_number=pr_number,
            head_sha=head_sha,
            hunk_map=hunk_map,
        ),
        backend=backend,
        model=model,
        tools=[get_diff_tool, verify_comment_line_tool],
    )


__all__: list[str] = [
    "assemble_orchestrator_system_prompt",
    "assemble_review_subagents",
    "assemble_user_prompt",
    "build_review_agent",
    "get_review_agent",
]
