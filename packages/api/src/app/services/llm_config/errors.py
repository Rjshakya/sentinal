"""Typed errors for the v3 pi model-config service.

Expected failures are values, never exceptions: callers discriminate
with ``isinstance``. Raising is reserved for programmer errors.
"""

from __future__ import annotations

from pydantic import BaseModel


class LLMConfigStoreError(BaseModel):
    """DB or catalog failure while serving the pi model config."""

    message: str

    def __str__(self) -> str:
        return self.message


__all__ = ["LLMConfigStoreError"]
