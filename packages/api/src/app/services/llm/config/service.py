"""LLM-config sub-service: the user's stored ``llm_configs`` row.

Entry points:

- :func:`testLLMConfig` — run a structured-output deep-agent probe
  against a candidate config. **Never raises.** Returns a
  :class:`LLMConfigTestResult` with exactly one of ``response`` /
  ``exception`` populated.
- :func:`saveUserLLMConfig` — pure upsert of the user's
  ``llm_configs`` row (one config per user). No probe — callers probe
  first, then save. Returns
  ``LLMConfigRecord | LLMConfigStoreError``; never raises.
- :func:`listUserLLMConfigs` — load the user's stored row (empty list
  when the user has none); the router redacts ``api_key``.

The DB session is owned by the caller (:class:`AsyncSession` is a
parameter, never opened here); committing is the caller's job too.

Error contract: expected failures are values, never exceptions.
"""

from __future__ import annotations

from datetime import UTC, datetime

from deepagents import create_deep_agent
from langchain.agents.structured_output import ProviderStrategy
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.models.llm_config import LLMConfigRecord
from app.services.llm.config.errors import LLMConfigStoreError
from app.services.llm.config.types import (
    LLMConfigProbeResult,
    LLMConfigTestResult,
)
from app.services.llm.errors import LLMConfigError
from app.services.llm.service import createLLMModel
from app.services.llm.types import LLMCtx
from app.utils.branded import ApiKey, BaseUrl, UserId

_PROBE_SYSTEM_PROMPT: str = (
    "You are a connectivity probe. Reply with exactly one JSON object "
    'matching this schema: {"reply": "<string>"}. No other text.'
)
"""System prompt for the LLM-config probe (emits the probe schema)."""


def _success(response: str) -> LLMConfigTestResult:
    return {"response": response, "exception": None}


def _failure(message: str) -> LLMConfigTestResult:
    return {"response": None, "exception": message}


def _build_candidate_ctx(
    *,
    provider: str,
    model_id: str,
    base_url: str,
    api_key: str,
) -> LLMCtx:
    """Build an in-memory :class:`LLMCtx` for a candidate config.

    The candidate's ``model`` / ``apiKey`` / ``baseUrl`` come from the
    request; the remaining knobs (headers / retries / rate limit) come
    from the global settings so a user-supplied credential still flows
    through Sentinel's rate limiter / retry policy.
    """
    return LLMCtx(
        model=f"{provider}:{model_id}",
        origin="user",
        apiKey=ApiKey(api_key) if api_key else None,
        baseUrl=BaseUrl(base_url) if base_url else None,
        defaultHeaders=dict(settings.llm_default_headers),
        maxRetries=settings.llm_max_retries,
        rateLimitRps=settings.llm_rate_limit_rps,
    )


async def testLLMConfig(
    *,
    provider: str,
    modelId: str,
    baseUrl: str,
    apiKey: str,
) -> LLMConfigTestResult:
    """Run a deep-agent structured-output probe; never raises.

    The probe runs a :func:`deepagents.create_deep_agent` instance
    against the candidate config with ``response_format`` bound to
    :class:`LLMConfigProbeResult` — the same structured-output path
    the review agents use. The agent is invoked with a single user
    message and instructed to emit the schema's ``reply`` without
    calling tools.

    The outcome is the validated ``structured_response``, or a
    failure string when anything went wrong (auth, network, empty
    body, model not found, provider 4xx like forced-tool-choice
    rejections, …).

    No callbacks are attached, so the probe produces no
    ``llm_call_started`` / ``llm_call_completed`` log lines and no
    Sentry noise. The tokens still show up in the provider's own
    usage dashboard.
    """
    try:
        ctx = _build_candidate_ctx(
            provider=provider,
            model_id=modelId,
            base_url=baseUrl,
            api_key=apiKey,
        )
    except Exception as exc:
        return _failure(f"invalid config: {type(exc).__name__}: {exc}")

    chat = createLLMModel(ctx)
    if isinstance(chat, LLMConfigError):
        return _failure(f"invalid config: {chat}")

    try:
        agent = create_deep_agent(
            model=chat,
            response_format=ProviderStrategy(LLMConfigProbeResult),
            system_prompt=_PROBE_SYSTEM_PROMPT,
        )
        result = await agent.ainvoke(
            {"messages": [{"role": "user", "content": "Hi there"}]}
        )
    except Exception as exc:
        return _failure(f"{type(exc).__name__}: {exc}")

    structured = (
        result.get("structured_response") if isinstance(result, dict) else None
    )
    if structured is None:
        return _failure("provider returned no structured output")

    try:
        parsed = LLMConfigProbeResult.model_validate(structured)
    except Exception as exc:
        return _failure(f"invalid structured output: {type(exc).__name__}: {exc}")

    return _success(f"structured output OK (reply={parsed.reply!r})")


async def saveUserLLMConfig(
    session: AsyncSession,
    *,
    userId: UserId,
    provider: str,
    modelId: str,
    baseUrl: str,
    apiKey: str,
) -> LLMConfigRecord | LLMConfigStoreError:
    """Upsert the user's ``llm_configs`` row; never raises.

    Replaces the user's existing row when one exists (one config per
    user). The caller owns the session and the commit.

    Returns:
        ``LLMConfigRecord`` on success; ``LLMConfigStoreError`` on any
        DB failure (read, insert/update, or refresh).
    """
    stmt = select(LLMConfigRecord).where(LLMConfigRecord.user_id == userId)
    try:
        existing = (await session.exec(stmt)).first()
        if existing is not None:
            existing.provider = provider
            existing.model_id = modelId
            existing.base_url = baseUrl
            existing.api_key = apiKey
            existing.updated_at = datetime.now(UTC)
            session.add(existing)
            await session.flush()
            await session.refresh(existing)
            return existing

        row = LLMConfigRecord(
            user_id=userId,
            provider=provider,
            model_id=modelId,
            base_url=baseUrl,
            api_key=apiKey,
        )
        session.add(row)
        await session.flush()
        await session.refresh(row)
        return row
    except Exception as exc:
        return LLMConfigStoreError(
            message=f"database error: {type(exc).__name__}: {exc}"
        )


async def listUserLLMConfigs(
    session: AsyncSession,
    userId: UserId,
) -> list[LLMConfigRecord]:
    """Return the user's stored :class:`LLMConfigRecord`, if any.

    The router redacts ``api_key`` before returning. The list is
    empty when the user has no row (one element at most — one config
    per user).
    """
    stmt = select(LLMConfigRecord).where(LLMConfigRecord.user_id == userId)
    row = (await session.exec(stmt)).first()
    return [row] if row is not None else []


__all__ = ["listUserLLMConfigs", "saveUserLLMConfig", "testLLMConfig"]