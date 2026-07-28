"""Review-agent factories.

The pipeline runs four independent ``create_deep_agent`` instances in
parallel — one summary agent and three severity-bucketed specialists
(security / correctness / style). There is no orchestrator. Each
agent gets the same shared tools (``get_diff``,
``verify_comment_line``) and the same sandbox backend, but its own
system prompt and ``response_format``.

The four results are combined by :func:`combine_review_results` into
a single :class:`ReviewResult` — verdict is a deterministic function
of the severities present, so no LLM is involved in the merge.

This module is pure: no I/O, no session, no clock. The chat model and
sandbox connection are passed in by the caller.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

from deepagents import create_deep_agent
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.tools import BaseTool
from langchain_e2b import AsyncE2BSandbox

from app.core.llm import LLMProviderStr, build_chat_model
from app.core.sandbox import BaseSandbox
from app.core.sandbox.e2b import E2BSandbox
from app.services.agent.models import (
    CodeCommentDraft,
    CorrectnessComments,
    ReviewResult,
    ReviewVerdictStr,
    SecurityComments,
    StyleComments,
)
from app.services.agent.prompts import (
    CORRECTNESS_SYSTEM_PROMPT,
    PR_SUMMARY_SYSTEM_PROMPT,
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


# --------------------------------------------------------------------------- #
# Combine step                                                                 #
# --------------------------------------------------------------------------- #


def _verdict_for(comments: Sequence[CodeCommentDraft]) -> ReviewVerdictStr:
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


def combine_review_results(
    *,
    summary_markdown: str,
    security: SecurityComments,
    correctness: CorrectnessComments,
    style: StyleComments,
) -> ReviewResult:
    """Merge the four agent outputs into one :class:`ReviewResult`.

    Comments are concatenated in severity order (P1 → P2 → P3) so the
    GitHub review renders with the most important findings first. The
    summary is the summarizer's markdown verbatim. The verdict is
    computed from the merged comments by :func:`_verdict_for`.

    No dedup. Each specialist stays in its own lane; in practice they
    look at different classes of bugs and rarely overlap. Adding a
    dedup pass here would need an LLM or fuzzy rules and isn't worth
    the complexity for the rare case.
    """
    comments: list[CodeCommentDraft] = [
        *security.List,
        *correctness.List,
        *style.List,
    ]
    return ReviewResult(
        comments=comments,
        summary=summary_markdown,
        verdict=_verdict_for(comments),
    )


# --------------------------------------------------------------------------- #
# Summary agent output extraction                                              #
# --------------------------------------------------------------------------- #


def extract_last_ai_text(result: object) -> str:
    """Return the content of the last ``AIMessage`` in ``result['messages']``.

    The summary agent does not use a ``response_format`` — its output
    is a free-form markdown block emitted as the last AI message.
    The other three agents do use ``response_format`` and their
    payloads are read from ``result['structured_response']`` directly.

    Raises:
        ReviewAgentReturnedNoStructuredResponseError: ``result`` is
            not a dict, has no ``messages`` list, has no ``AIMessage``
            in it, or the last ``AIMessage`` has empty content.
    """
    # Imported here to keep the helper's import surface small.
    from app.services.review.errors import (
        ReviewAgentReturnedNoStructuredResponseError,
    )
    from app.services.agent.helpers import extract_message_kinds

    if not isinstance(result, dict):
        raise ReviewAgentReturnedNoStructuredResponseError(
            message_kinds=extract_message_kinds(result),
        )
    messages = result.get("messages")
    if not isinstance(messages, list) or not messages:
        raise ReviewAgentReturnedNoStructuredResponseError(
            message_kinds=extract_message_kinds(messages),
        )
    last: BaseMessage | None = messages[-1]
    if not isinstance(last, AIMessage):
        raise ReviewAgentReturnedNoStructuredResponseError(
            message_kinds=extract_message_kinds(messages),
        )
    content = last.content
    if not isinstance(content, str) or not content.strip():
        raise ReviewAgentReturnedNoStructuredResponseError(
            message_kinds=extract_message_kinds(messages),
        )
    return content


# --------------------------------------------------------------------------- #
# Shared tool + backend wiring                                                 #
# --------------------------------------------------------------------------- #


def _build_shared_tools(
    *,
    sandbox: BaseSandbox,
    pr_number: int,
    head_sha: str,
    hunk_map: HunkMap,
) -> list[BaseTool]:
    """Return the tool list every review agent receives.

    ``get_diff`` reads the unified PR diff from the sandbox.
    ``verify_comment_line`` answers "is this ``(file, line, side)``
    anchor one that GitHub will accept?" against the parsed
    :data:`HunkMap`. The deepagents runtime inherits the backend
    tools (sandbox ``read_file`` / ``ls`` / ``execute``) separately.
    """
    return [
        make_get_diff_tool(sandbox=sandbox, pr_number=pr_number, head_sha=head_sha),
        make_verify_comment_line_tool(hunk_map=hunk_map),
    ]


def _build_backend(sandbox: E2BSandbox) -> AsyncE2BSandbox:
    """Wrap the E2B sandbox for the deepagents runtime.

    All four agents share the same backend instance — the connection
    is held by the fan-out step and reused by every concurrent
    ``ainvoke``.
    """
    return AsyncE2BSandbox(sandbox=sandbox.sandbox)


# --------------------------------------------------------------------------- #
# Per-agent factories                                                          #
# --------------------------------------------------------------------------- #


def build_summary_agent(
    *,
    model: BaseChatModel,
    backend: AsyncE2BSandbox,
    tools: Sequence[BaseTool],
) -> DeepAgentGraph:
    """Build the PR-summary deep-agent.

    No ``response_format``: the agent emits a single markdown block
    as its last AI message. The fan-out step extracts that text with
    :func:`extract_last_ai_text` and passes it to
    :func:`combine_review_results` as ``summary_markdown``.
    """
    return create_deep_agent(
        model=model,
        system_prompt=PR_SUMMARY_SYSTEM_PROMPT,
        backend=backend,
        tools=list(tools),
    )


def build_security_agent(
    *,
    model: BaseChatModel,
    backend: AsyncE2BSandbox,
    tools: Sequence[BaseTool],
) -> DeepAgentGraph:
    """Build the P1_CRITICAL security deep-agent."""
    return create_deep_agent(
        model=model,
        system_prompt=SECURITY_SYSTEM_PROMPT,
        backend=backend,
        response_format=SecurityComments,
        tools=list(tools),
    )


def build_correctness_agent(
    *,
    model: BaseChatModel,
    backend: AsyncE2BSandbox,
    tools: Sequence[BaseTool],
) -> DeepAgentGraph:
    """Build the P2_WARNING correctness deep-agent."""
    return create_deep_agent(
        model=model,
        system_prompt=CORRECTNESS_SYSTEM_PROMPT,
        backend=backend,
        response_format=CorrectnessComments,
        tools=list(tools),
    )


def build_style_agent(
    *,
    model: BaseChatModel,
    backend: AsyncE2BSandbox,
    tools: Sequence[BaseTool],
) -> DeepAgentGraph:
    """Build the P3_NITPICK style deep-agent."""
    return create_deep_agent(
        model=model,
        system_prompt=STYLE_SYSTEM_PROMPT,
        backend=backend,
        response_format=StyleComments,
        tools=list(tools),
    )


# --------------------------------------------------------------------------- #
# One-shot factory (all four agents + chat model + backend)                    #
# --------------------------------------------------------------------------- #


def build_review_agents(
    *,
    sandbox: E2BSandbox,
    pr_number: int,
    head_sha: str,
    provider: LLMProviderStr,
    llm_baseurl: str | None,
    llm_api_key: str,
    llm_model: str,
    hunk_map: HunkMap,
) -> tuple[
    DeepAgentGraph,
    DeepAgentGraph,
    DeepAgentGraph,
    DeepAgentGraph,
    BaseChatModel,
    AsyncE2BSandbox,
]:
    """Build the chat model, the shared backend, and the four review agents.

    Returns ``(summary, security, correctness, style, model, backend)``.
    The model and backend are returned alongside the agents so the
    caller can reuse them in log lines or in additional invocations
    without rebuilding the LLM client.
    """
    model = build_chat_model(
        provider=provider,
        base_url=llm_baseurl,
        api_key=llm_api_key,
        model=llm_model,
        headers={"cf-aig-gateway-id": "sentinal-ai-gateway"},
    )
    backend = _build_backend(sandbox)
    tools = _build_shared_tools(
        sandbox=sandbox,
        pr_number=pr_number,
        head_sha=head_sha,
        hunk_map=hunk_map,
    )
    log.info(
        "building review agents: model=%s",
        getattr(model, "model_name", "<unknown>"),
    )
    return (
        build_summary_agent(model=model, backend=backend, tools=tools),
        build_security_agent(model=model, backend=backend, tools=tools),
        build_correctness_agent(model=model, backend=backend, tools=tools),
        build_style_agent(model=model, backend=backend, tools=tools),
        model,
        backend,
    )


# --------------------------------------------------------------------------- #
# User prompt (sent to all four agents)                                        #
# --------------------------------------------------------------------------- #


def assemble_user_prompt(
    *,
    repo_name: str,
    repo_id: str,
    user_id: str,
    pr_number: int,
) -> str:
    """Build the user message sent to each of the four review agents.

    Pure formatting — no I/O, no LLM. The diff is no longer inlined;
    every agent calls the ``get_diff`` tool to read it from the
    sandbox.
    """
    return (
        f"Repo: {repo_name} (id={repo_id})\n"
        f"User: {user_id}\n"
        f"PR number: {pr_number}\n"
        f"\n"
        f"Call the `get_diff()` tool to read the PR diff before reviewing.\n"
    )


__all__: list[str] = [
    "assemble_user_prompt",
    "build_correctness_agent",
    "build_review_agents",
    "build_security_agent",
    "build_style_agent",
    "build_summary_agent",
    "combine_review_results",
    "extract_last_ai_text",
]
