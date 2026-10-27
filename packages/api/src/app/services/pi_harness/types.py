"""Types for the v3 pi agent harness.

Two frozen shapes:

- :class:`PiModel` — provider + model + key (+ optional thinking
  level): everything ``pi --print`` needs, as pure serializable data.
- :class:`PiRunResult` — the outcome of one ``pi --print`` run.
  Exactly one of ``text`` / ``error`` is non-``None``.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.utils.branded import ApiKey

ThinkingLevel = Literal["off", "minimal", "low", "medium", "high", "xhigh", "max"]
"""Allowed ``pi --thinking`` levels (clamped to the model by pi)."""

DEFAULT_TOOLS: tuple[str, ...] = ("read", "grep", "find", "ls")
"""Default tool allowlist: read-only reviewer (no bash/edit/write)."""


class PiModel(BaseModel):
    """Model selection for one pi run (mirrors ``LLMConfigCtx`` + thinking)."""

    model_config = ConfigDict(frozen=True)

    provider: str = Field(min_length=1, max_length=64)
    modelId: str = Field(min_length=1, max_length=255)
    apiKey: ApiKey
    thinking: ThinkingLevel | None = None


class PiRunResult(BaseModel):
    """Outcome of one ``pi --print`` run. Never raised, only returned."""

    model_config = ConfigDict(frozen=True)

    ok: bool
    text: str | None = None
    sessionId: str | None = None
    error: str | None = None


__all__ = [
    "DEFAULT_TOOLS",
    "PiModel",
    "PiRunResult",
    "ThinkingLevel",
]
