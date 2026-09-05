"""Per-user LLM-config sub-service.

Owns the ``llm_configs`` table: the connectivity probe
(:func:`testLLMConfig`), the pure upsert (:func:`saveUserLLMConfig`),
and the row read (:func:`listUserLLMConfigs`). The chat-model factory
itself lives in the parent :mod:`app.services.llm`.

Error contract: expected failures are values, never exceptions —
:func:`testLLMConfig` returns :class:`LLMConfigTestResult` and
:func:`saveUserLLMConfig` returns
``LLMConfigRecord | LLMConfigStoreError``.
"""

from app.services.llm.config.errors import LLMConfigStoreError
from app.services.llm.config.service import (
    listUserLLMConfigs,
    saveUserLLMConfig,
    testLLMConfig,
)
from app.services.llm.config.types import (
    LLMConfigProbeResult,
    LLMConfigTestResult,
    LLMConfigTestResultPublic,
)

__all__ = [
    "LLMConfigProbeResult",
    "LLMConfigStoreError",
    "LLMConfigTestResult",
    "LLMConfigTestResultPublic",
    "listUserLLMConfigs",
    "saveUserLLMConfig",
    "testLLMConfig",
]