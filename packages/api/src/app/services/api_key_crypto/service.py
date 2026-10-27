"""Fernet at-rest encryption for per-user provider API keys.

:class:`ApiKeyCipher` is a sync cipher: the Fernet key comes from the
environment (``API_KEY_ENCRYPTION_KEY``) and is passed at construction.
No salt — a Fernet key is already random, there is nothing to derive.
Encryption is microsecond CPU work with no I/O, so the methods stay
sync (callable from sync and async code alike).

- :meth:`ApiKeyCipher.encrypt` — plaintext :class:`ApiKey` in,
  :class:`EncryptedApiKey` token out for DB storage. Raises
  :class:`ValueError` on empty input (programmer error).
- :meth:`ApiKeyCipher.decrypt` — stored token in, plaintext
  :class:`ApiKey` or :class:`ApiKeyDecryptError` out. Expected
  failures (wrong key, tampered/foreign token) are values, never
  raised. Constructor failure (bad key material) raises
  :class:`ValueError` — fail fast at the edge.
"""

from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken

from app.services.api_key_crypto.errors import ApiKeyDecryptError
from app.services.api_key_crypto.types import EncryptedApiKey
from app.utils.branded import ApiKey


class ApiKeyCipher:
    """Sync Fernet cipher for at-rest provider API keys."""

    def __init__(self, apiKeyEncryptionKey: str) -> None:
        if not apiKeyEncryptionKey:
            raise ValueError("apiKeyEncryptionKey must be non-empty")
        try:
            self._fernet = Fernet(apiKeyEncryptionKey)
        except ValueError as exc:
            raise ValueError(
                "apiKeyEncryptionKey must be a 32-byte urlsafe-b64 Fernet key "
                f"(generate with Fernet.generate_key()): {exc}"
            ) from exc

    def encrypt(self, key: ApiKey) -> EncryptedApiKey:
        """Encrypt a plaintext provider key into a storable token."""
        if not key:
            raise ValueError("key must be non-empty")
        return EncryptedApiKey(
            self._fernet.encrypt(bytes(key, "utf-8")).decode("ascii")
        )

    def decrypt(self, token: EncryptedApiKey) -> ApiKey | ApiKeyDecryptError:
        """Decrypt a stored token back into a plaintext provider key."""
        try:
            return ApiKey(self._fernet.decrypt(bytes(token, "utf-8")).decode("utf-8"))
        except InvalidToken:
            return ApiKeyDecryptError(
                message="stored api key token is invalid "
                "(wrong encryption key or tampered value)"
            )
        except Exception as exc:
            return ApiKeyDecryptError(
                message=f"api key decrypt failed: {type(exc).__name__}: {exc}"
            )


__all__ = ["ApiKeyCipher"]
