"""Shared types for the per-user LLM config feature.

Two shapes are needed:

- :class:`LLMTestResult` — a TypedDict used inside the service layer
  (no Pydantic, no validation overhead) to carry the outcome of
  :func:`app.services.llm_config.test_user_llm_config`. Exactly one
  of ``response`` / ``exception`` is non-``None``.
- :class:`LLMTestResultPublic` — a Pydantic mirror of the TypedDict
  used at the API surface. Same shape, validated for the wire.
"""

from __future__ import annotations

from typing import TypedDict

from pydantic import BaseModel


class LLMTestResult(TypedDict, total=False):
    """Outcome of a single ``test_user_llm_config`` call.

    Exactly one of ``response`` / ``exception`` is non-``None``.
    ``response`` carries the LLM's reply text on a successful call;
    ``exception`` carries a human-readable error string on any
    failure (auth, network, empty body, etc.).
    """

    response: str | None
    exception: str | None


class LLMTestResultPublic(BaseModel):
    """Pydantic mirror of :class:`LLMTestResult` for the API surface."""

    response: str | None = None
    exception: str | None = None


__all__ = ["LLMTestResult", "LLMTestResultPublic"]
