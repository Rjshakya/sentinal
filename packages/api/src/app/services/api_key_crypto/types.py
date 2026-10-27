"""Branded token type for the at-rest API-key cipher."""

from __future__ import annotations

from typing import NewType

EncryptedApiKey = NewType("EncryptedApiKey", str)
"""Fernet token string: an encrypted provider API key, as stored in ``llmconfig``."""

__all__ = ["EncryptedApiKey"]
