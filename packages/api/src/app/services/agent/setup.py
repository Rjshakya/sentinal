"""Setup deep-agent.

A single-shot deepagent whose only mission is to install the
dependencies of a freshly-cloned repo. The agent lives inside the
caller's already-connected E2B sandbox, gets the repo path as its only
input, and emits a single structured :class:`SetupResult`.

The module is intentionally small and mirrors the shape of
:mod:`app.services.agent.review`:

- :func:`build_setup_agent` — composes the deepagent graph. Pure
  factory; takes explicit LLM params (no settings reads).
- :func:`run_setup` — the LLM-SDK edge. Calls the agent, times the
  run, validates the structured response, and returns a
  :class:`Result` so the pipeline orchestrator never has to handle
  an exception.

Persistence is the caller's concern. This module never imports a DB
driver and never writes to the filesystem except via the sandbox
backend the agent is given.
"""

from __future__ import annotations

import logging
import time

from deepagents import create_deep_agent
from e2b import AsyncSandbox
from langchain_e2b import AsyncE2BSandbox
from sqlmodel import or_, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.result import Err, Ok, Result
from app.models.enums import SandboxState
from app.models.sandbox import Sandbox as SandboxTable
from app.services.agent.models import SetupResult
from app.services.agent.prompts import SETUP_AGENT_SYSTEM_PROMPT
from app.services.agent.review import (
    CompiledDeepAgent,
    LLMProviderStr,
    build_chat_model,
)
from app.services.agent.setup_errors import (
    SetupAgentCrashed,
    SetupAgentReturnedNoStructuredResponse,
)
from app.services.sandbox_scripts.utils import repo_path, workspace_path

log = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Module-level configuration                                                  #
# --------------------------------------------------------------------------- #
#
# These are plain module globals on purpose. The setup agent is an
# isolated feature; we are not adding new env-driven settings to
# :class:`Settings` for it. If we later need to tune these at deploy
# time, this is the single file to edit.


SETUP_AGENT_MAX_STEPS: int = 30
"""Upper bound on LLM steps the deepagent may take before we abort.

Each step is one LLM call + tool execution. 30 covers: manifest
discovery, one bootstrap command, the install command, the verify
command, and a few retries. A genuine monorepo install can spike
beyond this; raise it per-deployment if needed."""


SETUP_AGENT_TIMEOUT_S: int = 900
"""Hard timeout (seconds) for the entire :func:`run_setup` call.

Wall-clock, measured on the host. The agent is aborted when this
elapses, regardless of :data:`SETUP_AGENT_MAX_STEPS`."""


# --------------------------------------------------------------------------- #
# Pure helpers                                                                #
# --------------------------------------------------------------------------- #


def assemble_setup_user_prompt(*, repo_id: str, repo_name: str, user_id: str) -> str:
    """Build the user prompt sent to the setup deepagent.

    Pure formatting — no I/O, no LLM. Split out of :func:`run_setup`
    so it is testable and the LLM-SDK edge stays minimal.
    """
    return (
        f"Repo: {repo_name} (id={repo_id})\n"
        f"User: {user_id}\n"
        f"The repo is cloned at {repo_path(repo_name)} "
        "inside the sandbox. Inspect the manifest(s), pick a manager, "
        "bootstrap any missing tooling, run the install, and verify. "
        "Then return a single SetupResult."
    )


def _extract_message_kinds(messages: object) -> tuple[str, ...]:
    """Return ``(type,)`` for each message in a deepagents messages list.

    Pure — no I/O. Used to populate the ``message_kinds`` field of
    :class:`SetupAgentReturnedNoStructuredResponse` so the caller can
    see *what* the agent produced before failing. Tolerant of any
    non-list input (returns an empty tuple) and of messages without a
    string ``type`` attribute.
    """
    if not isinstance(messages, list):
        return ()
    kinds: list[str] = []
    for message in messages:
        kind = getattr(message, "type", None)
        if isinstance(kind, str):
            kinds.append(kind)
    return tuple(kinds)


def validate_setup_response(
    result: object,
) -> Result[SetupResult, SetupAgentReturnedNoStructuredResponse]:
    """Extract and validate the agent's ``structured_response`` payload.

    Pure: takes the full ``agent.ainvoke()`` result, returns ``Ok``
    with a validated :class:`SetupResult` or ``Err`` with the
    variant that names the message kinds the agent did produce. The
    caller stamps :attr:`SetupResult.duration_s` separately — the
    timing lives at the LLM-SDK edge, not here.

    Contract:

    - ``result`` must be a dict-like (the deepagents return shape);
      anything else is treated as "no structured response".
    - The function pulls ``result["structured_response"]``. If the
      key is missing, the error variant carries the kinds of the
      messages the agent did emit, so the failure is diagnosable.
    - A non-``None`` structured response that is not a valid
      :class:`SetupResult` raises from
      :meth:`SetupResult.model_validate` and propagates to the
      orchestrator's outermost ``try / except`` — the agent emitted
      something we cannot interpret, which is treated as a generic
      pipeline crash.
    """
    if not isinstance(result, dict):
        return Err(
            SetupAgentReturnedNoStructuredResponse(
                message_kinds=_extract_message_kinds(result)
            )
        )
    structured = result.get("structured_response")
    if structured is None:
        return Err(
            SetupAgentReturnedNoStructuredResponse(
                message_kinds=_extract_message_kinds(result.get("messages"))
            )
        )
    return Ok(SetupResult.model_validate(structured))


# --------------------------------------------------------------------------- #
# DB queries                                                                  #
# --------------------------------------------------------------------------- #


async def active_sandbox(
    session: AsyncSession,
    user_id: str,
    repo_id: str,
) -> SandboxTable | None:
    """Return the active sandbox row for ``(user_id, repo_id)``, if any.

    An active sandbox is one whose state is ``STARTED``, ``PAUSED`` or
    ``STOPPED`` (i.e. anything except ``DELETED`` or ``ARCHIVED``).
    """
    query = select(SandboxTable).where(
        SandboxTable.repo_id == repo_id,
        SandboxTable.user_id == user_id,
        or_(
            SandboxTable.state == SandboxState.STARTED,
            SandboxTable.state == SandboxState.PAUSED,
            SandboxTable.state == SandboxState.STOPPED,
        ),
    )
    result = await session.exec(query)
    return result.first()


# --------------------------------------------------------------------------- #
# Backend                                                                     #
# --------------------------------------------------------------------------- #


def attach_sandbox_backend(sandbox: AsyncSandbox) -> AsyncE2BSandbox:
    """Wrap an already-connected E2B sandbox as a deepagents backend.

    Mirrors :func:`app.services.agent.review.attach_sandbox_backend` so
    the setup and review agents share the same backend shape. The
    returned object exposes ``read_file`` / ``write_file`` / ``execute``
    to the deepagent.
    """
    return AsyncE2BSandbox(sandbox=sandbox)


# --------------------------------------------------------------------------- #
# Agent factory                                                               #
# --------------------------------------------------------------------------- #


def build_setup_agent(
    *,
    sandbox: AsyncSandbox,
    llm_provider: LLMProviderStr,
    llm_base_url: str | None,
    llm_api_key: str,
    llm_model: str,
) -> CompiledDeepAgent:
    """Construct the setup deep agent.

    The agent has:

    - a chat model built by :func:`build_chat_model` from the four
      explicit LLM params (no settings reads inside the factory),
    - the E2B sandbox backend wrapping the caller's connected
      sandbox,
    - no subagents — the setup mission is single-shot,
    - a :class:`SetupResult` ``response_format`` so the final answer
      is captured as ``result["structured_response"]``.

    The returned graph is a compiled LangGraph state graph; call it
    via :py:meth:`CompiledStateGraph.ainvoke` (see :func:`run_setup`).
    """

    model = build_chat_model(
        provider=llm_provider,
        base_url=llm_base_url,
        api_key=llm_api_key,
        model=llm_model,
    )

    backend: AsyncE2BSandbox = attach_sandbox_backend(sandbox)

    log.info(
        "building setup deep agent: max_steps=%d timeout_s=%d",
        SETUP_AGENT_MAX_STEPS,
        SETUP_AGENT_TIMEOUT_S,
    )

    return create_deep_agent(
        model=model,
        system_prompt=SETUP_AGENT_SYSTEM_PROMPT,
        backend=backend,
        response_format=SetupResult,
    )


# --------------------------------------------------------------------------- #
# Entry point                                                                 #
# --------------------------------------------------------------------------- #


async def run_setup(
    *,
    repo_id: str,
    repo_name: str,
    user_id: str,
    sandbox: AsyncSandbox,
    llm_provider: LLMProviderStr,
    llm_base_url: str | None,
    llm_api_key: str,
    llm_model: str,
) -> Result[SetupResult, SetupAgentCrashed | SetupAgentReturnedNoStructuredResponse]:
    """Run the setup agent against a single repo — the LLM-SDK edge.

    The agent is built fresh for every call — deepagents' state is
    in-memory and short-lived, and a fresh build is cheaper than
    tracking per-repo state across calls. The caller's sandbox is
    reused; we never create a new one here.

    Wall-clock duration is measured on the host and stamped into
    :attr:`SetupResult.duration_s`. The single ``try / except`` in
    this function is the boundary into the LangChain SDK: any
    exception raised by ``agent.ainvoke`` is converted to
    :class:`SetupAgentCrashed` so the pipeline orchestrator never
    has to handle an exception from this layer.

    The four LLM args are passed through to :func:`build_setup_agent`
    — this function reads no settings.
    """

    agent: CompiledDeepAgent = build_setup_agent(
        sandbox=sandbox,
        llm_provider=llm_provider,
        llm_base_url=llm_base_url,
        llm_api_key=llm_api_key,
        llm_model=llm_model,
    )

    user_prompt = assemble_setup_user_prompt(
        repo_id=repo_id, repo_name=repo_name, user_id=user_id
    )

    log.info(
        "invoking setup agent: repo=%s user=%s max_steps=%d",
        repo_name,
        user_id,
        SETUP_AGENT_MAX_STEPS,
    )

    started: float = time.monotonic()
    try:
        result = await agent.ainvoke(
            {"messages": [{"role": "user", "content": user_prompt}]}
        )
    except Exception as exc:
        return Err(SetupAgentCrashed(cause=f"{type(exc).__name__}: {exc}"))
    duration_s: float = time.monotonic() - started

    return validate_setup_response(result).map(
        lambda parsed: parsed.model_copy(update={"duration_s": duration_s})
    )


__all__: list[str] = [
    "SETUP_AGENT_MAX_STEPS",
    "SETUP_AGENT_TIMEOUT_S",
    "assemble_setup_user_prompt",
    "attach_sandbox_backend",
    "build_setup_agent",
    "run_setup",
    "validate_setup_response",
]
