"""Closed error union for the setup agent pipeline.

Every error variant is a frozen dataclass with plain-value fields — no
exception instances, no live objects, no ORM rows. The shell layer
(the orchestrator's ``try / except`` and the protocol adapters'
internal try / except) is responsible for *building* the right variant
from whatever the underlying SDK raised.

The five variants correspond to the five stages of
:func:`app.services.agent.setup_pipeline.run_setup_pipeline`:

1. ``InstallationNotFound``         — DB lookup step
2. ``InstallTokenMintFailed``       — GitHub install-token mint
3. ``GitCloneFailed``               — sandbox ``git clone`` step
4. ``SetupAgentCrashed``            — LLM agent invocation
5. ``SetupAgentReturnedNoStructuredResponse`` — agent's response
                                             parsing step

``SetupPipelineError`` is the union. New failure modes get a new
variant; the existing call sites are then exhaustively updated (a
strict type checker will flag any ``match`` statement that doesn't
handle the new case).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Union


@dataclass(frozen=True, slots=True)
class InstallationNotFound:
    """The user's ``Installation`` row is missing or owned by another user."""

    installation_id: str
    user_id: str


@dataclass(frozen=True, slots=True)
class InstallTokenMintFailed:
    """Minting a GitHub installation token failed."""

    cause: str


@dataclass(frozen=True, slots=True)
class GitCloneFailed:
    """``git clone`` inside the sandbox exited non-zero."""

    exit_code: int
    output_tail: str


@dataclass(frozen=True, slots=True)
class SetupAgentCrashed:
    """The LLM agent invocation raised before producing a structured result."""

    cause: str


@dataclass(frozen=True, slots=True)
class SetupAgentReturnedNoStructuredResponse:
    """The LLM agent returned no ``structured_response`` key."""

    message_kinds: tuple[str, ...]


SetupPipelineError = Union[
    InstallationNotFound,
    InstallTokenMintFailed,
    GitCloneFailed,
    SetupAgentCrashed,
    SetupAgentReturnedNoStructuredResponse,
]


__all__ = [
    "GitCloneFailed",
    "InstallationNotFound",
    "InstallTokenMintFailed",
    "SetupAgentCrashed",
    "SetupAgentReturnedNoStructuredResponse",
    "SetupPipelineError",
]
