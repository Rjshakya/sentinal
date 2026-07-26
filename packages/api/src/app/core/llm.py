"""Shared chat-model factory.

This module owns the single place where Sentinel constructs a LangChain
chat model from provider / base_url / api_key / model. Both the review
and setup agents consume it, so the factory lives in ``app.core`` rather
than inside either service.
"""

from __future__ import annotations

from typing import Literal, Mapping, TypeAlias

from langchain_anthropic import ChatAnthropic
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.rate_limiters import InMemoryRateLimiter
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_openai import ChatOpenAI
from pydantic import SecretStr

LLMProviderStr: TypeAlias = Literal["openai", "anthropic", "google"]
"""Allowed values for LLM provider slugs.

Validated at chat-model construction time by :func:`build_chat_model`;
unknown values raise ``ValueError``."""


def build_chat_model(
    *,
    provider: LLMProviderStr,
    base_url: str | None,
    api_key: str,
    model: str,
    headers: Mapping[str, str] | None = None,
) -> BaseChatModel:
    """Construct a langchain chat model from the four LLM params.

    Pure factory — no I/O, no settings reads. The API key is wrapped in
    :class:`pydantic.SecretStr` to satisfy each provider's typed
    ``api_key`` parameter (langchain rejects bare ``str`` keys at
    type-check time). ``base_url`` is forwarded to providers that accept
    it (``None`` is a no-op for the others). Unknown providers raise
    ``ValueError``; this is a programmer error, not a pipeline failure
    mode.
    """
    secret: SecretStr = SecretStr(api_key)
    if provider == "openai":
        return ChatOpenAI(
            model=model,
            api_key=secret,
            base_url=base_url,
            max_retries=3,
            rate_limiter=InMemoryRateLimiter(requests_per_second=0.5),
            default_headers=headers,
        )
    if provider == "anthropic":
        # `timeout` and `stop` are pydantic Field aliases for
        # `default_request_timeout` and `stop_sequences`; both default to
        # ``None`` at runtime, but pyright's pydantic-aware checker
        # doesn't always pick that up from the alias. Pass them
        # explicitly so the call type-checks.
        return ChatAnthropic(
            model_name=model,
            api_key=secret,
            base_url=base_url,
            timeout=None,
            stop=None,
            max_retries=3,
        )

    if provider == "google":
        return ChatGoogleGenerativeAI(model=model, api_key=secret)

    raise ValueError(f"unsupported LLM provider: {provider}")


__all__: list[str] = ["LLMProviderStr", "build_chat_model"]
