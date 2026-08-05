"""Review-agent factories.

This module owns two parallel agent designs:

- **Legacy (deprecated).** :func:`build_review_agents` returns four
  independent ``create_deep_agent`` instances (summary / security /
  correctness / style). The workflow's old
  :func:`app.services.review.steps.invoke_review_agents_step`
  (plural) runs them in parallel via ``asyncio.gather`` and combines
  the results with :func:`combine_review_results`. Kept as a
  revert path; the new workflow calls the singular step instead.

- **New (production).** :func:`build_review_subagents` returns four
  ``SubAgent`` specs (TypedDicts); :func:`build_orchestrator_agent`
  returns one root deep-agent whose ``subagents=`` is the list from
  the first call. The new step
  :func:`app.services.review.steps.invoke_review_agent_step`
  (singular) ``ainvoke``s the orchestrator once. The orchestrator
  coordinates the four subagents, absorbs their failures, and emits a
  single :class:`ReviewResult`. The verdict field is recomputed
  deterministically in code from the merged comments.

Each chat model (one per subagent + the orchestrator) gets its own
:func:`app.core.llm_callbacks.make_llm_io_handler` so the log
stream can tell ``agent="orchestrator"`` from
``agent="summary" | "security" | "correctness" | "style"``.

This module is pure: no I/O, no session, no clock. The chat model
and sandbox connection are passed in by the caller.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import TypedDict

from deepagents import create_deep_agent
from deepagents.middleware.subagents import SubAgent
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.tools import BaseTool
from langchain_e2b import AsyncE2BSandbox

from app.core.llm import LLMConfig, build_chat_model
from app.core.sandbox import BaseSandbox
from app.core.sandbox.e2b import E2BSandbox
from app.services.agent.models import (
    CodeCommentDraft,
    CorrectnessComments,
    ReviewResult,
    ReviewVerdictStr,
    SecurityComments,
    StyleComments,
    SummaryResult,
)
from app.services.agent.prompts import (
    CORRECTNESS_SYSTEM_PROMPT,
    ORCHESTRATOR_SYSTEM_PROMPT,
    PR_SUMMARY_SYSTEM_PROMPT,
    SECURITY_SYSTEM_PROMPT,
    STYLE_SYSTEM_PROMPT,
)
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
    computed from the merged comments by :func:`verdict_for`.

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
        verdict=verdict_for(comments),
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
    diff's parsed hunk map is also written to
    ``/home/user/tmp/{pr_number}/{head_sha}/diff.json`` in the
    sandbox; the agents read it directly via the deepagents
    backend's ``read_file`` tool when they need to validate or
    re-anchor a ``(file, line, side)`` comment. The deepagents
    runtime inherits the backend tools (sandbox ``read_file`` /
    ``ls`` / ``execute``) separately.

    ``hunk_map`` is currently unused by the tool list itself — it
    is only passed in so the workflow step can hand the same parsed
    structure to both the agent step (for diff.json regeneration
    parity) and the server-side :func:`filter_drafts` backstop.
    """
    return [
        make_get_diff_tool(sandbox=sandbox, pr_number=pr_number, head_sha=head_sha),
    ]


def _build_backend(sandbox: E2BSandbox) -> AsyncE2BSandbox:
    """Wrap the E2B sandbox for the deepagents runtime.

    All four agents share the same backend instance — the connection
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
) -> DeepAgentGraph:
    """Build the PR-summary deep-agent.

    ``response_format`` is :class:`SummaryResult` — the agent emits a
    single ``summary`` markdown block as its structured response. The
    fan-out step reads it from ``structured_response`` and passes it
    to :func:`combine_review_results` as ``summary_markdown``.
    """
    return create_deep_agent(
        model=model,
        system_prompt=PR_SUMMARY_SYSTEM_PROMPT,
        backend=backend,
        response_format=SummaryResult,
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


class SubAgentsModels(TypedDict):
    summary_model: BaseChatModel
    security_model: BaseChatModel
    correctness_model: BaseChatModel
    style_model: BaseChatModel


def create_review_llm_models(
    llm_config: LLMConfig,
) -> SubAgentsModels:

    summary_model = build_chat_model(
        config=llm_config,
    )

    security_model = build_chat_model(
        config=llm_config,
    )

    correctness_model = build_chat_model(
        config=llm_config,
    )

    style_model = build_chat_model(
        config=llm_config,
    )

    return SubAgentsModels(
        summary_model=summary_model,
        security_model=security_model,
        correctness_model=correctness_model,
        style_model=style_model,
    )


def build_review_agents(
    *,
    sandbox: E2BSandbox,
    pr_number: int,
    head_sha: str,
    models: SubAgentsModels,
) -> tuple[
    DeepAgentGraph,
    DeepAgentGraph,
    DeepAgentGraph,
    DeepAgentGraph,
]:
    """Build the chat model, the shared backend, and the four review agents.

    Returns ``(summary, security, correctness, style, model, backend)``.
    The model returned as the 5th tuple element is the summary agent's
    chat model — kept for backward compatibility with callers that
    reused the model. The three specialist agents own their own chat
    model instances so each can carry its own per-agent callback
    handler.

    When ``settings.llm_log_io_enabled`` is true, each agent gets a
    :class:`app.core.llm_callbacks.LLMIOCallbackHandler` attached to
    the chat model. LangChain threads the model's callbacks through
    every inner run, so one outer ``ainvoke`` produces N
    ``llm_call_started`` / ``llm_call_completed`` log lines plus the
    interleaved ``tool_call_started`` / ``tool_call_completed`` lines
    for ``get_diff`` (and the deepagents backend's ``read_file`` /
    ``ls`` / ``execute`` tools the agent uses to inspect
    ``diff.json``). When the flag is off, no handler is attached
    and there is zero per-call overhead.

    ``repo_id`` and ``repo_name`` are required for the handler's
    correlation context; ``workflow_id`` is optional and is filled in
    by :func:`app.services.review.steps.invoke_review_agents_step`
    from ``DBOS.workflow_id``.
    """
    backend = _build_backend(sandbox)
    tools = _build_shared_tools(
        sandbox=sandbox,
        pr_number=pr_number,
        head_sha=head_sha,
    )

    summary_model = models["summary_model"]
    security_model = models["security_model"]
    correctness_model = models["correctness_model"]
    style_model = models["style_model"]

    log.info(
        "building review agents: model=%s",
        getattr(summary_model, "model_name", "<unknown>"),
    )

    return (
        build_summary_agent(model=summary_model, backend=backend, tools=tools),
        build_security_agent(model=security_model, backend=backend, tools=tools),
        build_correctness_agent(model=correctness_model, backend=backend, tools=tools),
        build_style_agent(model=style_model, backend=backend, tools=tools),
    )


# --------------------------------------------------------------------------- #
# New design: orchestrator + subagents                                          #
# --------------------------------------------------------------------------- #
#
# These factories back the new ``invoke_review_agent_step`` (singular).
# They are deliberately separate from the legacy
# ``build_review_agents`` above so the old step keeps working as a
# revert path.


def build_review_subagents(
    *,
    sandbox: E2BSandbox,
    pr_number: int,
    head_sha: str,
    model: BaseChatModel,
) -> list[SubAgent]:
    """Build the four review subagents for the orchestrator.

    Returns a list of :class:`SubAgent` TypedDicts in the order
    ``[summary, security, correctness, style]``. Each subagent
    owns its own chat model (and therefore its own per-agent
    callback handler).

    The summary subagent has no ``response_format`` and emits a
    single markdown block as its last AI message. The three
    severity-bucketed subagents have ``response_format`` set to
    the corresponding ``*Comments`` Pydantic model so the
    orchestrator receives a structured response from each.

    ``description`` is what the orchestrator reads when deciding
    which subagent to invoke; it is intentionally short and lane-
    specific.
    """

    summary_subagent: SubAgent = SubAgent(
        name="summary",
        description=(
            "Writes a markdown summary of what the PR does. Returns "
            "a SummaryResult object with a single `summary` field "
            "containing the markdown block. Use this subagent for "
            "the ReviewResult.summary field."
        ),
        system_prompt=PR_SUMMARY_SYSTEM_PROMPT,
        model=model,
        response_format=SummaryResult,
        tools=[
            make_get_diff_tool(sandbox=sandbox, pr_number=pr_number, head_sha=head_sha),
        ],
    )

    security_subagent: SubAgent = SubAgent(
        name="security",
        description=(
            "Finds P1_CRITICAL security issues (injection, secrets, "
            "auth bypass, crypto misuse). Returns a "
            "SecurityComments object with a `list` of CodeCommentDraft; "
            "every entry already has severity='P1_CRITICAL'."
        ),
        system_prompt=SECURITY_SYSTEM_PROMPT,
        model=model,
        response_format=SecurityComments,
        tools=[
            make_get_diff_tool(sandbox=sandbox, pr_number=pr_number, head_sha=head_sha),
        ],
    )

    correctness_subagent: SubAgent = SubAgent(
        name="correctness",
        description=(
            "Finds P2_WARNING correctness issues (off-by-one, race "
            "conditions, swallowed exceptions, broken error handling). "
            "Returns a CorrectnessComments object with a `list` of "
            "CodeCommentDraft; every entry already has "
            "severity='P2_WARNING'."
        ),
        system_prompt=CORRECTNESS_SYSTEM_PROMPT,
        model=model,
        response_format=CorrectnessComments,
        tools=[
            make_get_diff_tool(sandbox=sandbox, pr_number=pr_number, head_sha=head_sha),
        ],
    )

    style_subagent: SubAgent = SubAgent(
        name="style",
        description=(
            "Finds P3_NITPICK style / lint issues a linter would flag. "
            "Returns a StyleComments object with a `list` of "
            "CodeCommentDraft; every entry already has "
            "severity='P3_NITPICK'."
        ),
        system_prompt=STYLE_SYSTEM_PROMPT,
        model=model,
        response_format=StyleComments,
        tools=[
            make_get_diff_tool(sandbox=sandbox, pr_number=pr_number, head_sha=head_sha),
        ],
    )

    return [summary_subagent, security_subagent, correctness_subagent, style_subagent]


def build_orchestrator_agent(
    *,
    model: BaseChatModel,
    backend: AsyncE2BSandbox,
    subagents: Sequence[SubAgent],
    tools: Sequence[BaseTool],
) -> DeepAgentGraph:
    """Build the root deep-agent that coordinates the four subagents.

    The orchestrator's ``response_format`` is :class:`ReviewResult`:
    its LLM is told in :data:`ORCHESTRATOR_SYSTEM_PROMPT` to assemble
    the four subagent outputs (three structured comment lists plus
    the summary markdown) into a single ``ReviewResult``. The verdict
    field is overwritten in code by the workflow step
    :func:`app.services.review.steps.invoke_review_agent_step`,
    so whatever the LLM puts there is discarded.

    Failure handling: the orchestrator is told to absorb subagent
    failures (its tool result is an error message) by substituting
    an empty result and continuing. The DBOS step therefore does
    not retry on a single subagent's failure.
    """
    return create_deep_agent(
        model=model,
        system_prompt=ORCHESTRATOR_SYSTEM_PROMPT,
        backend=backend,
        subagents=list(subagents),
        response_format=ReviewResult,
        tools=list(tools),
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
    "build_orchestrator_agent",
    "build_review_agents",
    "build_review_subagents",
    "build_security_agent",
    "build_style_agent",
    "build_summary_agent",
    "combine_review_results",
    "verdict_for",
]
