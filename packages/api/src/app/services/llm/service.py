"""LLM service: ctx-driven, provider-agnostic chat-model factory.

Entry points:

- :func:`createDefaultLLMContext` — build a :class:`LLMCtx` from settings.
- :func:`createUserLLMContext` — build a :class:`LLMCtx` from the user's
  stored ``llm_configs`` row (fresh DB query; no borrowing from the
  ``app.services.llm_config`` service).
- :func:`createLLMModel` — build the LangChain chat model
  (:class:`langchain_core.language_models.BaseChatModel`) for a ctx;
  fresh implementation over ``langchain.chat_models.init_chat_model``
  (no delegation to :mod:`app.core.llm`).

Error contract: **no function in this module raises.** Every expected
failure is a returned value: the per-user creator returns
``LLMCtx | LLMContextError`` (no stored row, DB read failure) and
:func:`createLLMModel` returns ``BaseChatModel | LLMConfigError``
(malformed ``"provider:model"`` string or provider-construction
failure). Callers discriminate with ``isinstance``.

Credentials: :attr:`LLMCtx.apiKey` / :attr:`LLMCtx.baseUrl` are carried on
the ctx and forwarded to the model factory; ``None`` defers to the
provider's native env-var resolution.

Naming convention: this package intentionally uses **camelCase**
identifiers — the same convention as :mod:`app.services.sandbox`.
"""

from __future__ import annotations

from typing import Any

from langchain.chat_models import init_chat_model
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.rate_limiters import InMemoryRateLimiter
from pydantic import SecretStr
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.models.llm_config import LLMConfigRecord
from app.services.llm.errors import LLMConfigError, LLMContextError
from app.services.llm.types import (
    ApiKey,
    BaseUrl,
    LLMCtx,
    UserId,
)


def createDefaultLLMContext() -> LLMCtx:
    """Build a :class:`LLMCtx` from the global :class:`Settings`.

    Picks up ``LLM_MODEL`` / ``LLM_API_KEY`` / ``LLM_BASE_URL`` /
    ``LLM_DEFAULT_HEADERS`` / ``LLM_MAX_RETRIES`` / ``LLM_RATE_LIMIT_RPS``.
    The LLM env vars are validated at app startup, so no gate lives
    here.
    """
    return LLMCtx(
        model=settings.llm_model,
        apiKey=ApiKey(settings.llm_api_key) if settings.llm_api_key else None,
        baseUrl=BaseUrl(settings.llm_base_url) if settings.llm_base_url else None,
        defaultHeaders=dict(settings.llm_default_headers),
        maxRetries=settings.llm_max_retries,
        rateLimitRps=settings.llm_rate_limit_rps,
    )


async def createUserLLMContext(
    session: AsyncSession,
    userId: UserId,
) -> LLMCtx | LLMContextError:
    """Build a :class:`LLMCtx` from the user's stored ``llm_configs`` row.

    Runs its own query against :class:`LLMConfigRecord` — the per-user
    service :mod:`app.services.llm_config` is intentionally not reused.
    The user's ``model`` / ``apiKey`` / ``baseUrl`` are taken from the
    row; the remaining knobs (headers / retries / rate limit) come from
    the global settings, so a user-supplied credential still flows
    through Sentinel's rate limiter / retry policy.

    Returns:
        ``LLMCtx`` on success; ``LLMContextError`` when the user has no
        row or the DB read fails (the error carries ``userId``). Never
        raises.
    """
    stmt = select(LLMConfigRecord).where(LLMConfigRecord.user_id == userId)
    try:
        row = (await session.exec(stmt)).first()
    except Exception as exc:
        return LLMContextError(
            message=f"failed to load llm config: {type(exc).__name__}: {exc}",
            userId=userId,
        )

    if row is None:
        return LLMContextError(
            message=f"no llm config for user {userId!r}",
            userId=userId,
        )

    return LLMCtx(
        model=f"{row.provider}:{row.model_id}",
        apiKey=ApiKey(row.api_key) if row.api_key else None,
        baseUrl=BaseUrl(row.base_url) if row.base_url else None,
        defaultHeaders=dict(settings.llm_default_headers),
        maxRetries=settings.llm_max_retries,
        rateLimitRps=settings.llm_rate_limit_rps,
    )


def createLLMModel(ctx: LLMCtx) -> BaseChatModel | LLMConfigError:
    """Build the LangChain chat model for a :class:`LLMCtx`.

    Fresh implementation over ``langchain.chat_models.init_chat_model`` —
    no delegation to :mod:`app.core.llm`. Applies the ctx's knobs
    uniformly: ``maxRetries``, an :class:`InMemoryRateLimiter` when
    ``rateLimitRps`` is positive, ``baseUrl``, ``defaultHeaders``, and a
    :class:`SecretStr`-wrapped key. Provider extras are applied for
    behavior parity: OpenAI ``gpt-5.6`` models use the Responses API,
    DeepSeek models force ``json_object`` response format. Pure sync —
    no I/O.

    Returns:
        ``BaseChatModel`` on success; ``LLMConfigError`` when
        ``ctx.model`` is not a valid ``"provider:model"`` string or the
        resolved provider rejects the configuration. Never raises.
    """
    if ":" not in ctx.model:
        return LLMConfigError(
            f"LLMCtx.model must be a 'provider:model' string, got {ctx.model!r}"
        )
    provider, model_id = ctx.model.split(":", 1)

    init_kwargs: dict[str, Any] = {"max_retries": ctx.maxRetries}
    if ctx.rateLimitRps is not None and ctx.rateLimitRps > 0:
        init_kwargs["rate_limiter"] = InMemoryRateLimiter(
            requests_per_second=ctx.rateLimitRps
        )
    if ctx.baseUrl:
        init_kwargs["base_url"] = ctx.baseUrl
    if ctx.defaultHeaders:
        init_kwargs["default_headers"] = dict(ctx.defaultHeaders)

    extra: dict[str, Any] = {}
    if provider == "openai" and model_id.startswith("gpt-5.6"):
        extra = {"use_responses_api": True, "output_version": "responses/v1"}
    if model_id.startswith("deepseek"):
        extra["extra_body"] = {"response_format": {"type": "json_object"}}

    try:
        return init_chat_model(
            model=ctx.model,
            api_key=SecretStr(ctx.apiKey) if ctx.apiKey else None,
            **init_kwargs,
            **extra,
        )
    except ValueError as exc:
        return LLMConfigError(str(exc))


__all__ = ["createDefaultLLMContext", "createLLMModel", "createUserLLMContext"]
