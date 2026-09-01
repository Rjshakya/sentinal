"""LLM service: provider-agnostic chat-model factory + per-user config.

Submodules:

- :func:`createDefaultLLMContext` — settings-driven :class:`LLMCtx`.
- :func:`createUserLLMContext` — per-user :class:`LLMCtx` from the user's
  stored ``llm_configs`` row (fresh DB query).
- :func:`createLLMModel` — build the LangChain chat model
  (:class:`langchain_core.language_models.BaseChatModel`) for a ctx.
- :mod:`.config` — sub-service: the user's stored ``llm_configs``
  row (probe, upsert, list).

Error contract: **no function in this package raises.** The default
creator returns :class:`LLMCtx` directly (the LLM env vars are
validated at app startup); the per-user creator returns
``LLMCtx | LLMContextError`` (no stored row, DB read failure); and
:func:`createLLMModel` returns ``BaseChatModel | LLMConfigError`` —
expected failures are values, never exceptions.

Naming convention: this package intentionally uses **camelCase**
identifiers — the same convention as :mod:`app.services.sandbox`.
"""

from app.services.llm.config import (
    LLMConfigProbeResult,
    LLMConfigStoreError,
    LLMConfigTestResult,
    LLMConfigTestResultPublic,
    listUserLLMConfigs,
    saveUserLLMConfig,
    testLLMConfig,
)
from app.services.llm.errors import LLMConfigError, LLMContextError
from app.services.llm.service import (
    createDefaultLLMContext,
    createLLMModel,
    createUserLLMContext,
)
from app.services.llm.types import (
    ApiKey,
    BaseUrl,
    LLMCtx,
    UserId,
)

__all__ = [
    "ApiKey",
    "BaseUrl",
    "LLMConfigError",
    "LLMConfigProbeResult",
    "LLMConfigStoreError",
    "LLMConfigTestResult",
    "LLMConfigTestResultPublic",
    "LLMCtx",
    "LLMContextError",
    "UserId",
    "createDefaultLLMContext",
    "createLLMModel",
    "createUserLLMContext",
    "listUserLLMConfigs",
    "saveUserLLMConfig",
    "testLLMConfig",
]