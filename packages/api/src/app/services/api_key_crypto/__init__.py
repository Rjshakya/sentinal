"""At-rest API-key encryption (``app.services.api_key_crypto``).

Sync Fernet cipher for per-user provider API keys. The key comes from
the environment and is passed at construction; nothing here reads
settings, touches the DB, or logs.
"""

from app.services.api_key_crypto.errors import ApiKeyDecryptError
from app.services.api_key_crypto.service import ApiKeyCipher
from app.services.api_key_crypto.types import EncryptedApiKey

__all__ = [
    "ApiKeyCipher",
    "ApiKeyDecryptError",
    "EncryptedApiKey",
]
