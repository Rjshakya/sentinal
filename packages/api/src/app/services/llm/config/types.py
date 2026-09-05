"""Types for the per-user LLM-config sub-service.

Three shapes:

- :class:`LLMConfigTestResult` — a TypedDict used inside the service
  layer (no Pydantic, no validation overhead) to carry the outcome of
  :func:`app.services.llm.config.service.testLLMConfig`. Exactly one
  of ``response`` / ``exception`` is non-``None``.
- :class:`LLMConfigTestResultPublic` — a Pydantic mirror of the
  TypedDict used at the API surface. Same shape, validated for the
  wire.
- :class:`LLMConfigProbeResult` — the structured-output schema the
  probe agent must emit (``reply``), validated after every probe call.
"""

from __future__ import annotations

from typing import TypedDict

from pydantic import BaseModel, Field


class LLMConfigProbeResult(BaseModel):
    """Structured-output schema for the LLM-config connectivity probe."""

    reply: str = Field(description="Agent's reply")


class LLMConfigTestResult(TypedDict, total=False):
    """Outcome of a single :func:`testLLMConfig` call.

    Exactly one of ``response`` / ``exception`` is non-``None``.
    ``response`` carries the validated probe reply on success;
    ``exception`` carries a human-readable error string on any
    failure (auth, network, empty body, model not found, provider
    4xx, …).
    """

    response: str | None
    exception: str | None


class LLMConfigTestResultPublic(BaseModel):
    """Pydantic mirror of :class:`LLMConfigTestResult` for the API surface."""

    response: str | None = None
    exception: str | None = None


__all__ = [
    "LLMConfigProbeResult",
    "LLMConfigTestResult",
    "LLMConfigTestResultPublic",
]