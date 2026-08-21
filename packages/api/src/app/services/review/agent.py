"""Review-agent factories.

This module owns the two parallel review agents:

- :func:`build_summary_agent` — the PR-summarizer deep-agent, emitting a
  ``SummaryResult`` (markdown summary).
- :func:`build_comments_agent` — the comments deep-agent, emitting a
  ``ReviewComments`` list with mixed severities (P1_CRITICAL security
  findings, P2_WARNING correctness findings, P3_NITPICK style findings)
  from a file-by-file workflow over the per-file diff chunks.

The workflow's per-lane steps
(:func:`app.services.review.steps.invoke_agent.invoke_summary_agent_step`
and :func:`app.services.review.steps.invoke_agent.invoke_comments_agent_step`)
run them in parallel and combine the results with
:func:`combine_review_results`.

Each chat model (one per agent) gets its own
:func:`app.core.llm_callbacks.make_llm_io_handler` so the log
stream can tell ``agent="summarizer"`` from ``agent="comments"``.

Structured output is normally ``response_format``: langchain binds the
schema as a tool and forces ``tool_choice="any"``. OpenAI-compatible
endpoints that reject forced tool choice (DeepSeek returns HTTP 400 for
``tool_choice="required"``) use text-JSON mode instead.

This module is pure: no I/O, no session, no clock. The chat model
and sandbox connection are passed in by the caller.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any, TypedDict

from deepagents import create_deep_agent
from langchain.agents.middleware.types import AgentMiddleware
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.tools import BaseTool
from langchain_e2b import AsyncE2BSandbox

from app.core.llm import LLMConfig, build_chat_model
from app.core.sandbox import BaseSandbox
from app.core.sandbox.e2b import E2BSandbox
from app.services.agent.models import (
    CodeCommentDraft,
    ReviewComments,
    ReviewResult,
    ReviewVerdictStr,
    SummaryResult,
)
from app.services.agent.prompts import (
    PR_SUMMARY_SYSTEM_PROMPT,
    REVIEW_COMMENTS_SYSTEM_PROMPT,
)
from app.services.review.helpers import get_review_diff_dir_path
from app.services.review.middleware import build_review_middleware
from app.services.review.tools import make_get_diff_tool
from app.services.review.types import DeepAgentGraph

log = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Combine step                                                                 #
# --------------------------------------------------------------------------- #


def verdict_for(comments: Sequence[CodeCommentDraft]) -> ReviewVerdictStr:
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


_SEVERITY_RANK: dict[str, int] = {
    "P1_CRITICAL": 0,
    "P2_WARNING": 1,
    "P3_NITPICK": 2,
}


def combine_review_results(
    *,
    summary_markdown: str,
    comments: ReviewComments,
) -> ReviewResult:
    """Merge the two agent outputs into one :class:`ReviewResult`.

    Comments are sorted in severity order (P1 → P2 → P3) so the
    GitHub review renders with the most important findings first. The
    summary is the summarizer's markdown verbatim. The verdict is
    computed from the merged comments by :func:`verdict_for`.

    No dedup. The single comments agent is asked not to repeat
    itself; adding a dedup pass here would need an LLM or fuzzy rules
    and isn't worth the complexity for the rare case.
    """
    return ReviewResult(
        comments=sorted(
            comments.List,
            key=lambda draft: _SEVERITY_RANK.get(draft.severity, len(_SEVERITY_RANK)),
        ),
        summary=summary_markdown,
        verdict=verdict_for(comments.List),
    )


# --------------------------------------------------------------------------- #
# Shared tool + backend wiring                                                 #
# --------------------------------------------------------------------------- #


def _build_shared_tools(
    *,
    sandbox: BaseSandbox,
    pr_number: int,
    head_sha: str,
) -> list[BaseTool]:
    """Return the tool list every review agent receives.

    ``get_diff`` reads the unified PR diff from the sandbox. The
    split step also writes ``overview.md`` and the per-file annotated
    chunks under ``splitted_diffs/`` next to ``file.diff``; the
    agents read those via the deepagents backend's ``read_file`` /
    ``ls`` tools (inherited separately).
    """
    return [
        make_get_diff_tool(sandbox=sandbox, pr_number=pr_number, head_sha=head_sha),
    ]


def _build_backend(sandbox: E2BSandbox) -> AsyncE2BSandbox:
    """Wrap the E2B sandbox for the deepagents runtime.

    Both agents share the same backend instance — the connection
    is held by the fan-out step and reused by every concurrent
    ``ainvoke``.
    """
    return AsyncE2BSandbox(sandbox=sandbox.sandbox, workdir="/home/user")


# --------------------------------------------------------------------------- #
# Per-agent factories                                                          #
# --------------------------------------------------------------------------- #


def build_summary_agent(
    *,
    model: BaseChatModel,
    backend: AsyncE2BSandbox,
    tools: Sequence[BaseTool],
    middleware: list[AgentMiddleware[Any, None, Any]],
) -> DeepAgentGraph:
    """Build the PR-summary deep-agent.

    ``response_format`` is :class:`SummaryResult` — the agent emits a
    single ``summary`` markdown block as its structured response. The
    fan-out step reads it from ``structured_response`` and passes it
    to :func:`combine_review_results` as ``summary_markdown``.

    The shared middleware stack
    (:func:`app.services.review.middleware.build_review_middleware`)
    wraps the model call with retries and caps model/tool calls per run.
    """
    return create_deep_agent(
        model=model,
        system_prompt=PR_SUMMARY_SYSTEM_PROMPT,
        backend=backend,
        response_format=SummaryResult,
        tools=list(tools),
        middleware=middleware,
    )


def build_comments_agent(
    *,
    model: BaseChatModel,
    backend: AsyncE2BSandbox,
    tools: Sequence[BaseTool],
    middleware: list[AgentMiddleware[Any, None, Any]],
) -> DeepAgentGraph:
    """Build the comments deep-agent (all severities in one review).

    ``response_format`` is :class:`ReviewComments` — the agent emits
    one list of :class:`CodeCommentDraft` entries with mixed
    severities (P1_CRITICAL security findings, P2_WARNING correctness
    findings, P3_NITPICK style findings). The prompt drives a
    file-by-file workflow over the per-file chunks in ``splitted_diffs/``
    (anchoring comments to gutter-visible lines only) and delegates the
    individual passes to the ``task`` tool's ``general-purpose``
    subagent when the PR is large. The fan-out step validates the result
    and hands it to :func:`combine_review_results`.

    The shared middleware stack
    (:func:`app.services.review.middleware.build_review_middleware`)
    wraps the model call with retries and caps model/tool calls per run.
    """
    return create_deep_agent(
        model=model,
        system_prompt=REVIEW_COMMENTS_SYSTEM_PROMPT,
        backend=backend,
        response_format=ReviewComments,
        tools=list(tools),
        middleware=middleware,
    )


# --------------------------------------------------------------------------- #
# One-shot factory (both agents + chat models + backend)                       #
# --------------------------------------------------------------------------- #


class ReviewAgentsModels(TypedDict):
    summary_model: BaseChatModel
    comments_model: BaseChatModel


def create_review_llm_models(
    llm_config: LLMConfig,
) -> ReviewAgentsModels:
    """Build the two chat models (one per agent).

    Each agent owns its own chat model instance so each can carry its
    own per-agent callback handler.
    """
    return ReviewAgentsModels(
        summary_model=build_chat_model(config=llm_config),
        comments_model=build_chat_model(config=llm_config),
    )


def build_review_agents(
    *,
    sandbox: E2BSandbox,
    pr_number: int,
    head_sha: str,
    models: ReviewAgentsModels,
) -> tuple[DeepAgentGraph, DeepAgentGraph]:
    """Build the shared backend, tools, and the two review agents.

    Returns ``(summary, comments)``. The summary agent owns the
    ``summary_model``; the comments agent owns ``comments_model`` —
    each carries its own per-agent callback handler.

    When ``settings.llm_log_io_enabled`` is true, each agent gets a
    :class:`app.core.llm_callbacks.LLMIOCallbackHandler` attached to
    the chat model. LangChain threads the model's callbacks through
    every inner run, so one outer ``ainvoke`` produces N
    ``llm_call_started`` / ``llm_call_completed`` log lines plus the
    interleaved ``tool_call_started`` / ``tool_call_completed`` lines
    for ``get_diff`` (and the deepagents backend's ``read_file`` /
    ``ls`` / ``execute`` tools the agent uses to inspect the diff
    artefacts in the sandbox). When the flag is off, no handler is
    attached and there is zero per-call overhead.
    """
    backend = _build_backend(sandbox)
    tools = _build_shared_tools(
        sandbox=sandbox,
        pr_number=pr_number,
        head_sha=head_sha,
    )

    summary_model = models["summary_model"]
    comments_model = models["comments_model"]
    middleware = build_review_middleware()

    log.info(
        "building review agents: model=%s",
        getattr(summary_model, "model_name", "<unknown>"),
    )

    return (
        build_summary_agent(
            model=summary_model,
            backend=backend,
            tools=tools,
            middleware=middleware,
        ),
        build_comments_agent(
            model=comments_model,
            backend=backend,
            tools=tools,
            middleware=middleware,
        ),
    )


# --------------------------------------------------------------------------- #
# User prompt (sent to both agents)                                            #
# --------------------------------------------------------------------------- #


def assemble_user_prompt(
    *,
    repo_name: str,
    repo_id: str,
    user_id: str,
    pr_number: int,
    head_sha: str,
) -> str:
    """Build the user message sent to each of the two review agents.

    Pure formatting — no I/O, no LLM. The diff is not inlined; the
    message carries the concrete Diff dir path (with ``overview.md``,
    ``splitted_diffs/``, and ``file.diff``) so the agents never have
    to discover it.
    """
    diff_dir = get_review_diff_dir_path(pr_number, head_sha)
    return (
        f"Repo: {repo_name} (id={repo_id})\n"
        f"User: {user_id}\n"
        f"PR number: {pr_number}\n"
        f"Head SHA: {head_sha}\n"
        f"Diff dir: {diff_dir}/\n"
        f"\n"
        f"The PR diff artefacts live in the Diff dir above: read "
        f"overview.md first, then the per-file chunks under "
        f"splitted_diffs/ (file.diff is the raw unified diff; the "
        f"get_diff() tool reads it).\n"
    )


__all__: list[str] = [
    "assemble_user_prompt",
    "build_comments_agent",
    "build_review_agents",
    "build_summary_agent",
    "combine_review_results",
    "verdict_for",
]
