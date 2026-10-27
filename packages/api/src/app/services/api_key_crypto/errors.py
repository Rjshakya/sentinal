"""Error values for the at-rest API-key cipher."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class ApiKeyDecryptError(BaseModel):
    """A stored token that could not be decrypted (wrong key, tampered value)."""

    model_config = ConfigDict(frozen=True)

    message: str


__all__ = ["ApiKeyDecryptError"]
