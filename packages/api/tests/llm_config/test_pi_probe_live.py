"""Live-sandbox test for the v3 pi probe.

Spins up a real E2B sandbox and runs ``pi --print`` through
:func:`app.services.llm_config.service.runPiProbe` with the
opencode-go provider — no mocks, no durable runtime. Requires
``E2B_API_KEY`` and ``LLM_API_KEY`` (an opencode-go key); skips
without them. Each success run spends real model credit and takes
~1-2 minutes.

Run: cd packages/api && uv run pytest tests/llm_config/test_pi_probe_live.py -v
"""

from __future__ import annotations

import pytest

from app.core.config import settings
from app.services.llm_config.service import runPiProbe
from app.services.llm_config.types import LLMConfigCtx
from app.utils.branded import ApiKey, UserId

_TEST_PROVIDER = "opencode-go"
_TEST_MODEL = "muse-spark-1.3-contributor"
_TEST_USER = UserId("pi-probe-test")
_INVALID_KEY = ApiKey("pi-test-invalid-key")


def _require_live_env() -> str:
    """Return the live API key, skipping when the env is incomplete."""
    if not settings.e2b_api_key:
        pytest.skip("E2B_API_KEY is not set; live probe test needs it")
    if not settings.llm_api_key:
        pytest.skip("LLM_API_KEY is not set; live probe test needs it")
    return settings.llm_api_key


async def test_probe_succeeds_with_valid_key() -> None:
    """The probe passes and the key never appears in the output."""
    api_key = _require_live_env()
    ctx = LLMConfigCtx(
        provider=_TEST_PROVIDER,
        modelId=_TEST_MODEL,
        apiKey=ApiKey(api_key),
    )
    result = await runPiProbe(ctx=ctx, userId=_TEST_USER)
    assert result.ok is True, f"probe failed: {result.error}"
    assert result.output is not None and result.output.strip() != ""
    assert api_key not in result.output


async def test_probe_fails_with_bad_key() -> None:
    """The probe fails closed on a bad key and reports the error."""
    if not settings.e2b_api_key:
        pytest.skip("E2B_API_KEY is not set; live probe test needs it")
    ctx = LLMConfigCtx(
        provider=_TEST_PROVIDER,
        modelId=_TEST_MODEL,
        apiKey=_INVALID_KEY,
    )
    result = await runPiProbe(ctx=ctx, userId=_TEST_USER)
    assert result.ok is False
    assert result.error is not None and result.error.strip() != ""
