"""Runtime Secrets Manager reader (I/O at import-adjacent edge).

Lambda caps total function environment at 4KB, so large secret values
(such as ``GITHUB_APP_PRIVATE_KEY``) are not injected as env vars. The
template passes only ``APP_SECRET_STORE`` (the secret name); this module
fetches that JSON secret once per process and serves keys from it.

Local runs are unaffected: callers must prefer ``Settings`` values first
and call :func:`app_secrets` only as a fallback, so machines without
``APP_SECRET_STORE`` never make a network call.
"""

from __future__ import annotations

import base64
import json
import os
from functools import lru_cache
from typing import Any

import boto3

APP_SECRET_STORE_ENV = "APP_SECRET_STORE"


def _decode_secret_payload(response: Any) -> str:
    """Return the secret string from a ``get_secret_value`` response."""
    if not isinstance(response, dict):
        raise ValueError("Unexpected Secrets Manager response shape")
    if "SecretString" in response:
        secret = response["SecretString"]
        if not isinstance(secret, str) or not secret:
            raise ValueError("Empty SecretString in Secrets Manager response")
        return secret
    if "SecretBinary" in response:
        binary = response["SecretBinary"]
        if isinstance(binary, str):
            binary = binary.encode("utf-8")
        if not isinstance(binary, bytes | bytearray) or not binary:
            raise ValueError("Empty SecretBinary in Secrets Manager response")
        return base64.b64decode(bytes(binary)).decode("utf-8")
    raise ValueError("No SecretString or SecretBinary in Secrets Manager response")


@lru_cache
def app_secrets() -> dict[str, Any]:
    """Return the app secret JSON object, fetched once per process.

    Raises:
        ValueError: ``APP_SECRET_STORE`` is unset, the secret is not
            JSON, or the JSON is not an object.
    """
    store = os.environ.get(APP_SECRET_STORE_ENV, "")
    if not store:
        raise ValueError(f"No {APP_SECRET_STORE_ENV}")

    client: Any = boto3.client("secretsmanager")
    payload = _decode_secret_payload(client.get_secret_value(SecretId=store))

    parsed: Any = json.loads(payload)
    if not isinstance(parsed, dict):
        raise ValueError("App secret JSON is not an object")
    return dict(parsed)


__all__ = ["APP_SECRET_STORE_ENV", "app_secrets"]
