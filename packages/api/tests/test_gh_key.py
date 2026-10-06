"""Live shape tests for the GitHub App private key pipeline.

Unlike the rest of the suite, these tests hit the REAL Secrets Manager
secret via the REAL :func:`app.core.secrets.app_secrets` — no stubs, no
fakes. They assert the stored key text has exactly the shape the
production decoder requires:

- fetch succeeds, value present and non-empty,
- single line with zero whitespace characters,
- valid base64 that decodes to a PEM (``-----BEGIN`` … ``-----END``).

They skip (not fail) when ``APP_SECRET_STORE`` is unset, so offline
runs and CI without AWS credentials stay green. Run live with::

    $env:APP_SECRET_STORE = 'sentinel-dev/app'
    uv run pytest tests/test_gh_key.py -q    # from packages/api/
"""

from __future__ import annotations

import base64
import binascii
import os

import pytest
from botocore.exceptions import ClientError

from app.core.config import settings
from app.core.secrets import (
    DEFAULT_SECRET_STORE_REGION,
    SECRET_STORE_REGION_ENV,
    _resolve_secret_store_region,
    app_secrets,
)
from app.services.github.client import getGithubAppPrivateKey

_NEEDS_STORE = pytest.mark.skipif(
    not os.environ.get("APP_SECRET_STORE", ""),
    reason="APP_SECRET_STORE unset; live secret test skipped",
)

_KEY_NAME = "GITHUB_APP_PRIVATE_KEY"


def _live_key_text() -> str:
    """Fetch the live key text and narrow it to ``str``."""
    app_secrets.cache_clear()
    raw = app_secrets().get(_KEY_NAME, "")
    assert isinstance(raw, str) and raw, "secret has no usable key text"
    return raw


def _assert_key_shape(raw: str) -> str:
    """Assert the stored text shape; return the decoded PEM."""
    assert "\n" not in raw and "\r" not in raw, "key text must be single-line"
    assert not any(c.isspace() for c in raw), "key text must have no whitespace"
    try:
        pem = base64.b64decode(raw, validate=True).decode("utf-8")
    except (binascii.Error, ValueError, UnicodeDecodeError) as exc:
        pytest.fail(f"key text is not valid base64 PEM text: {exc}")
    assert pem.startswith("-----BEGIN"), "decoded key has no PEM header"
    assert "-----END" in pem, "decoded key has no PEM footer"
    return pem


@_NEEDS_STORE
def test_live_private_key_shape() -> None:
    """Live secret fetches and has decodable PEM shape."""
    _assert_key_shape(_live_key_text())


@_NEEDS_STORE
def test_client_decode_matches_live_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Prod client decode path returns the live PEM (Lambda path)."""
    monkeypatch.setattr(settings, "github_app_private_key", "")
    app_secrets.cache_clear()
    pem = getGithubAppPrivateKey()
    assert pem.startswith("-----BEGIN"), "client did not return live PEM"
    assert "-----END" in pem, "client PEM missing footer"


def test_region_explicit_arg_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    """Explicit argument beats every env source."""
    monkeypatch.setenv(SECRET_STORE_REGION_ENV, "eu-west-1")
    monkeypatch.setenv("AWS_REGION", "ap-south-1")
    assert _resolve_secret_store_region("eu-central-1") == "eu-central-1"


def test_region_template_env_used(monkeypatch: pytest.MonkeyPatch) -> None:
    """SECRET_STORE_REGION env wins when no argument is given."""
    monkeypatch.setenv(SECRET_STORE_REGION_ENV, "eu-west-1")
    monkeypatch.delenv("AWS_REGION", raising=False)
    assert _resolve_secret_store_region(None) == "eu-west-1"


def test_region_runtime_env_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    """Lambda runtime AWS_REGION is the fallback (Lambda path)."""
    monkeypatch.delenv(SECRET_STORE_REGION_ENV, raising=False)
    monkeypatch.setenv("AWS_REGION", "ap-south-1")
    assert _resolve_secret_store_region(None) == "ap-south-1"


def test_region_safe_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """No configuration anywhere still resolves deterministically."""
    monkeypatch.delenv(SECRET_STORE_REGION_ENV, raising=False)
    monkeypatch.delenv("AWS_REGION", raising=False)
    assert _resolve_secret_store_region(None) == DEFAULT_SECRET_STORE_REGION


@_NEEDS_STORE
def test_wrong_region_fails_live(monkeypatch: pytest.MonkeyPatch) -> None:
    """Wrong region cannot find the secret (proves region control)."""
    monkeypatch.setenv(SECRET_STORE_REGION_ENV, "eu-west-1")
    app_secrets.cache_clear()
    try:
        app_secrets()
    except ClientError as exc:
        assert exc.response["Error"]["Code"] == "ResourceNotFoundException", (
            f"expected not-found in wrong region, got: {exc}"
        )
    else:
        pytest.fail("fetch in wrong region unexpectedly succeeded")
