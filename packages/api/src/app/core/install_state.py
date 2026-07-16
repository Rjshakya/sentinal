"""HMAC-signed state for the GitHub App install flow.

The dashboard calls :func:`sign` to mint a short-lived token that carries
the WorkOS ``user_id`` through GitHub's install → setup-URL redirect. The
setup callback calls :func:`verify` to recover the ``user_id`` and
confirm the token hasn't been tampered with or expired.

Format (stdlib only — no JWT lib):

    base64url(payload) "." base64url(hmac_sha256(secret, payload))

where ``payload`` is the UTF-8 string ``"{user_id}|{exp_unix_seconds}"``.

Both halves are URL-safe base64 with stripped padding. The HMAC is
compared in constant time. Any malformed input, bad signature, or
expired token returns ``None`` from :func:`verify` — the caller should
treat that as a bad state and abort the install.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import time

DEFAULT_TTL_SECONDS = 600


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64url_decode(text: str) -> bytes:
    padding = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + padding)


def sign(user_id: str, secret: str, *, ttl_seconds: int = DEFAULT_TTL_SECONDS) -> str:
    """Return a signed token for ``user_id`` valid for ``ttl_seconds``."""
    if not user_id or not isinstance(user_id, str):
        raise ValueError("user_id must be a non-empty string")
    if not secret:
        raise ValueError("secret must be a non-empty string")

    exp = int(time.time()) + int(ttl_seconds)
    payload = f"{user_id}|{exp}".encode("utf-8")
    mac = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).digest()
    return f"{_b64url_encode(payload)}.{_b64url_encode(mac)}"


def verify(token: str, secret: str) -> str | None:
    """Return the ``user_id`` if ``token`` is valid and unexpired, else ``None``."""
    if not token or not isinstance(token, str) or not secret:
        return None
    if "." not in token:
        return None

    payload_b64, _, mac_b64 = token.partition(".")
    if not payload_b64 or not mac_b64:
        return None

    try:
        payload = _b64url_decode(payload_b64)
        provided_mac = _b64url_decode(mac_b64)
    except (ValueError, TypeError):
        return None

    expected_mac = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).digest()
    if not hmac.compare_digest(provided_mac, expected_mac):
        return None

    try:
        decoded = payload.decode("utf-8")
    except UnicodeDecodeError:
        return None

    user_id, _, exp_str = decoded.rpartition("|")
    if not user_id or not exp_str:
        return None

    try:
        exp = int(exp_str)
    except ValueError:
        return None

    if exp < int(time.time()):
        return None

    return user_id
