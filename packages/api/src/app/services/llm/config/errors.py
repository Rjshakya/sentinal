"""Typed errors for the LLM-config sub-service.

- :class:`LLMConfigStoreError` — a DB write failure while persisting
  the user's ``llm_configs`` row. Returned (never raised) by
  :func:`app.services.llm.config.service.saveUserLLMConfig` as the
  error variant of its ``LLMConfigRecord | LLMConfigStoreError`` union.

The probe path :func:`testLLMConfig` never raises at all — it returns
:class:`LLMConfigTestResult` with ``exception`` populated instead, so
the router always receives the same envelope regardless of the
internal failure mode.
"""

from __future__ import annotations

from pydantic import BaseModel


class LLMConfigStoreError(BaseModel):
    """DB write failure while persisting the user's ``llm_configs`` row."""

    message: str

    def __str__(self) -> str:
        return self.message


__all__ = ["LLMConfigStoreError"]