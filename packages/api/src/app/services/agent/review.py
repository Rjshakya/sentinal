"""Deep-Agent review pipeline.

The review agent is a :func:`create_deep_agent` graph with three
specialist subagents (``security``, ``correctness``, ``style``) and a
structured output schema (:class:`ReviewResult`). It runs inside the
caller's already-active E2B sandbox so the agent can read the
surrounding repo, not just the diff.

The module is intentionally small:

- :func:`build_chat_model`        — pure factory; takes explicit
                                   provider / base_url / api_key /
                                   model. No settings reads.
- :func:`attach_sandbox_backend` — wraps an ``AsyncSandbox`` for deepagents.
- :func:`build_review_agent`     — composes the graph.
- :func:`run_review`             — single-call convenience that runs
                                   the graph and returns a typed
                                   :class:`ReviewResult`.

The persistence layer is *not* in this module. The caller (the
service in :mod:`app.services.review`) takes the returned
``ReviewResult`` and writes it to the DB. Keeping the split lets us
swap the agent without touching DB code and vice versa.
"""

from __future__ import annotations

import logging
from typing import Literal, TypeAlias, cast

from deepagents import create_deep_agent
from deepagents.backends.protocol import BackendProtocol
from deepagents.middleware.subagents import SubAgent
from e2b import AsyncSandbox
from langchain_anthropic import ChatAnthropic
from langchain_core.language_models import BaseChatModel
from langchain_core.runnables import Runnable
from langchain_e2b import AsyncE2BSandbox
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_openai import ChatOpenAI
from pydantic import SecretStr

from app.core.config import settings
from app.services.agent.models import ReviewResult
from app.services.agent.prompts import (
    CORRECTNESS_SYSTEM_PROMPT,
    REVIEW_ORCHESTRATOR_SYSTEM_PROMPT,
    SECURITY_SYSTEM_PROMPT,
    STYLE_SYSTEM_PROMPT,
)

log = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Type aliases                                                                #
# --------------------------------------------------------------------------- #


#: Allowed values for :func:`build_chat_model`'s ``provider`` argument.
#: Also matches :attr:`Settings.llm_provider` (a plain ``str``) at the
#: boundary — the call sites use :func:`typing.cast` to bridge, and an
#: unknown value surfaces as :class:`ValueError` from
#: :func:`build_chat_model`'s dispatch.
LLMProviderStr = Literal["openai", "anthropic", "google"]


#: Output of :func:`create_deep_agent` — a compiled LangGraph state graph.
#: We type it loosely because deepagents doesn't export a public alias.
CompiledDeepAgent: TypeAlias = Runnable


# --------------------------------------------------------------------------- #
# Configuration                                                               #
# --------------------------------------------------------------------------- #


def build_chat_model(
    *,
    provider: LLMProviderStr,
    base_url: str | None,
    api_key: str,
    model: str,
) -> ChatOpenAI | ChatAnthropic | ChatGoogleGenerativeAI:
    """Build a LangChain chat model. Pure — no settings reads.

    The caller is expected to gate on configuration presence (the
    existing :attr:`Settings.llm_configured` check, or its module
    equivalent) before calling this. Missing keys surface as a
    :class:`ValueError` from the underlying LangChain client, not from
    this function.

    ``base_url`` is only honored when ``provider == "openai"``; the
    Anthropic and Google clients talk to their own endpoints and
    ignore it. Pass ``None`` for non-OpenAI providers.

    Raises:
        ValueError: when ``provider`` is not one of the supported
            values (:data:`LLMProviderStr`).
    """
    if provider == "openai":
        return ChatOpenAI(
            base_url=base_url,
            api_key=SecretStr(api_key),
            model=model,
        )
    if provider == "anthropic":
        # ``model_name`` is the public alias for ``ChatAnthropic.model``
        # (pydantic Field alias with populate_by_name=True). The alias
        # is what the inferred stub exports. ``timeout`` and ``stop``
        # default to ``None`` in the field defs but pyright reports
        # them as required because of the alias — hence the
        # type: ignore[call-arg].
        return ChatAnthropic(
            base_url=base_url,
            model_name=model,
            api_key=SecretStr(api_key),
            timeout=None,
            stop=None,
        )
    if provider == "google":
        return ChatGoogleGenerativeAI(
            model=model,
            google_api_key=api_key,
        )


def create_e2b_sandbox_backend(sandbox: AsyncSandbox):
    return AsyncE2BSandbox(sandbox=sandbox)


# --------------------------------------------------------------------------- #
# Sandbox backend                                                             #
# --------------------------------------------------------------------------- #


def attach_sandbox_backend(sandbox: AsyncSandbox) -> BackendProtocol | BackendProtocol:
    """Wrap an already-connected E2B sandbox as a deepagents backend.

    We pass an ``e2b.AsyncSandbox`` (the caller's connected handle)
    through to ``langchain_e2b.AsyncE2BSandbox``. The deepagents
    ``BaseSandbox`` protocol only exposes async tool methods, so the
    async variant is the right shape — the sync ``E2BSandbox`` would
    block the event loop on every command.

    The returned object is consumed by
    ``create_deep_agent(backend=...)`` to expose ``read_file`` /
    ``write_file`` / ``execute`` tools to the agent.
    """

    return AsyncE2BSandbox(sandbox=sandbox)


# --------------------------------------------------------------------------- #
# Subagent specs                                                              #
# --------------------------------------------------------------------------- #


def _subagent_spec(
    *,
    name: str,
    description: str,
    system_prompt: str,
) -> SubAgent:
    """Build a declarative subagent spec for ``create_deep_agent``.

    Each subagent inherits the parent's ``backend`` (the E2B sandbox),
    so they all share the same filesystem and execute tools. They do
    not need their own ``tools=`` or ``backend=`` — leaving them
    empty lets the orchestrator's tools flow through.

    The return type is the deepagents ``SubAgent`` TypedDict.
    """
    return SubAgent(
        name=name,
        description=description,
        system_prompt=system_prompt,
    )


# --------------------------------------------------------------------------- #
# Agent factory                                                               #
# --------------------------------------------------------------------------- #


def build_review_agent(
    *,
    sandbox: AsyncSandbox,
    llm_provider: LLMProviderStr,
    llm_base_url: str | None,
    llm_api_key: str,
    llm_model: str,
) -> CompiledDeepAgent:
    """Construct the review deep agent.

    The agent has:

    - a single chat model built by :func:`build_chat_model` from the
      four explicit LLM params (no settings reads inside the factory),
    - the ``E2BSandbox`` backend wrapping the caller's connected
      sandbox,
    - three subagents (``security``, ``correctness``, ``style``),
    - a :class:`ReviewResult` ``response_format`` so the orchestrator's
      final answer is captured as ``result["structured_response"]``.

    The returned graph is a compiled LangGraph state graph; call it
    via :py:meth:`CompiledStateGraph.ainvoke` (see :func:`run_review`).
    """

    model: BaseChatModel = build_chat_model(
        provider=llm_provider,
        base_url=llm_base_url,
        api_key=llm_api_key,
        model=llm_model,
    )
    backend = attach_sandbox_backend(sandbox)

    subagents: list[SubAgent] = [
        _subagent_spec(
            name="security",
            description=(
                "Security reviewer. Emits only P1_CRITICAL findings "
                "(auth bypass, injection, secrets, SSRF, unsafe "
                "deserialization, path traversal)."
            ),
            system_prompt=SECURITY_SYSTEM_PROMPT,
        ),
        _subagent_spec(
            name="correctness",
            description=(
                "Correctness reviewer. Emits only P2_WARNING findings "
                "(bugs, race conditions, broken edge cases, missing "
                "error handling)."
            ),
            system_prompt=CORRECTNESS_SYSTEM_PROMPT,
        ),
        _subagent_spec(
            name="style",
            description=(
                "Style reviewer. Emits only P3_NITPICK findings "
                "(naming, dead code, idioms, small refactors)."
            ),
            system_prompt=STYLE_SYSTEM_PROMPT,
        ),
    ]

    log.info(
        "building review deep agent: provider=%s model=%s base_url=%s subagents=%s",
        llm_provider,
        llm_model,
        llm_base_url,
        [s["name"] for s in subagents],
    )

    return create_deep_agent(
        model=model,
        system_prompt=REVIEW_ORCHESTRATOR_SYSTEM_PROMPT,
        tools=[],
        backend=backend,
        subagents=subagents,
        response_format=ReviewResult,
    )


# --------------------------------------------------------------------------- #
# Entry point                                                                 #
# --------------------------------------------------------------------------- #


async def run_review(
    *,
    diff: str,
    repo_id: str,
    repo_name: str,
    user_id: str,
    sandbox: AsyncSandbox,
) -> ReviewResult:
    """Run the review agent against a single diff.

    The agent is built fresh for every call. Deepagents' state is
    in-memory and short-lived; we don't need (or want) cross-call
    memory. If we later add persistent memory, this is the place to
    thread a ``thread_id`` through the config.

    Returns a validated :class:`ReviewResult` (never a dict, never a
    raw model output) so the persistence layer can rely on the type.
    """
    agent: CompiledDeepAgent = build_review_agent(
        sandbox=sandbox,
        llm_provider=cast(LLMProviderStr, settings.llm_provider),
        llm_base_url=settings.llm_base_url or None,
        llm_api_key=settings.llm_api_key,
        llm_model=settings.llm_model,
    )

    user_prompt = (
        f"Repo: {repo_name} (id={repo_id})\n"
        f"User: {user_id}\n"
        f"Diff (unified):\n"
        f"```diff\n{diff}\n```\n\n"
        "The repo is cloned at /home/user/sentinel-workspace/"
        f"{repo_name} inside the sandbox. Use the sandbox filesystem "
        "and execute tools to read the changed files in full and any "
        "surrounding context you need.\n\n"
        "When you are done, return a single ReviewResult with the "
        "merged comments, a short summary, and a verdict."
    )

    log.info(
        "invoking review agent: repo=%s user=%s diff_chars=%d",
        repo_name,
        user_id,
        len(diff),
    )
    result = await agent.ainvoke(
        {"messages": [{"role": "user", "content": user_prompt}]}
    )

    raw = result.get("structured_response")
    if raw is None:
        # deepagents guarantees this key when response_format is set,
        # but guard anyway so a model-side hiccup surfaces as a clean
        # error rather than a NoneType crash downstream.
        raise RuntimeError(
            "review agent returned no structured_response "
            f"(messages={[m.type for m in result.get('messages', [])]})"
        )

    return ReviewResult.model_validate(raw)
