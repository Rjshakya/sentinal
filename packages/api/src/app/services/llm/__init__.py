"""LLM service: provider-agnostic chat-model factory.

Entry points:

- :func:`createDefaultLLMContext` — settings-driven :class:`LLMCtx`.
- :func:`createUserLLMContext` — per-user :class:`LLMCtx` from the user's
  stored ``llm_configs`` row (fresh DB query).
- :func:`createLLMModel` — build the LangChain chat model
  (:class:`langchain_core.language_models.BaseChatModel`) for a ctx.

Error contract: **no function in this package raises.** The creators
return ``LLMCtx | LLMContextError`` and :func:`createLLMModel` returns
``BaseChatModel | LLMConfigError`` — expected failures are values, never
exceptions.

Naming convention: this package intentionally uses **camelCase**
identifiers — the same convention as :mod:`app.services.sandbox`.
"""

from app.services.llm.errors import LLMConfigError
from app.services.llm.service import (
    createDefaultLLMContext,
    createLLMModel,
    createUserLLMContext,
)
from app.services.llm.types import (
    ApiKey,
    BaseUrl,
    LLMCtx,
    LLMContextError,
    UserId,
)

__all__ = [
    "ApiKey",
    "BaseUrl",
    "LLMConfigError",
    "LLMCtx",
    "LLMContextError",
    "UserId",
    "createDefaultLLMContext",
    "createLLMModel",
    "createUserLLMContext",
]