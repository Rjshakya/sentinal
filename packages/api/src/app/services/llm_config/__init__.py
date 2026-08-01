"""Per-user LLM config service.

Public surface:

- :func:`test_user_llm_config` — run a two-message connectivity
  probe against a candidate LLM config. **Never raises.** Returns
  a :class:`LLMTestResult` with exactly one of ``response`` /
  ``exception`` populated.
- :func:`upsert_user_llm_config` — probe first, then on success
  replace the user's existing ``llm_configs`` row (one config per
  user). Returns ``(record_or_None, test_result)`` so the router
  can build the response envelope.
- :func:`list_user_llm_configs` — load the user's stored row, with
  ``api_key`` redacted by the router layer.
- :func:`resolve_active_llm_config` — load the user's stored
  ``LLMConfigRecord`` and reconstruct a :class:`app.core.llm.LLMConfig`
  for the review workflow. Raises
  :class:`NoActiveLLMConfigError` when the user has no row.

The service is plain async functions; it is not a DBOS workflow. The
upsert is a single transaction (one row read + one row insert or
update); it is short enough to not need a durable workflow.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from uuid import UUID

from langchain_core.messages import HumanMessage, SystemMessage
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.db import async_session_maker
from app.core.llm import LLMConfig, build_chat_model
from app.models.llm_config import LLMConfigRecord

from app.services.llm_config.errors import NoActiveLLMConfigError
from app.services.llm_config.types import LLMTestResult

log = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Pure helpers                                                                  #
# --------------------------------------------------------------------------- #


def _build_user_config(
    *,
    provider: str,
    model_id: str,
    base_url: str,
    api_key: str,
) -> LLMConfig:
    """Build an :class:`LLMConfig` for the user-supplied inputs.

    The :attr:`LLMConfig.model` field is the combined
    ``"provider:model"`` string consumed by
    :func:`langchain.chat_models.init_chat_model`. The other knobs
    (headers, max_retries, rate_limit_rps) are taken from the
    global ``Settings`` so a user-supplied credential still flows
    through Sentinel's rate limiter / retry policy.
    """
    from app.core.config import settings

    return LLMConfig(
        model=f"{provider}:{model_id}",
        api_key=api_key or None,
        base_url=base_url or None,
        headers=dict(settings.llm_default_headers),
        max_retries=settings.llm_max_retries,
        rate_limit_rps=settings.llm_rate_limit_rps,
    )


def _result(response: str) -> LLMTestResult:
    return {"response": response, "exception": None}


def _failure(message: str) -> LLMTestResult:
    return {"response": None, "exception": message}


# --------------------------------------------------------------------------- #
# Connectivity probe                                                            #
# --------------------------------------------------------------------------- #


async def test_user_llm_config(
    *,
    provider: str,
    model_id: str,
    base_url: str,
    api_key: str,
) -> LLMTestResult:
    """Send a two-message probe and return the outcome without raising.

    The probe is a single ``ainvoke`` with one ``SystemMessage``
    ("Reply with a single word.") and one ``HumanMessage``
    ("hi"). The result is the assistant's reply text, or a
    failure string if anything went wrong (auth, network, empty
    body, model not found, etc.).

    No callbacks are attached, so the probe produces no
    ``llm_call_started`` / ``llm_call_completed`` log lines and
    no Sentry noise. The tokens still show up in the provider's
    own usage dashboard.
    """
    try:
        config = _build_user_config(
            provider=provider,
            model_id=model_id,
            base_url=base_url,
            api_key=api_key,
        )
    except Exception as exc:
        return _failure(f"invalid config: {type(exc).__name__}: {exc}")

    try:
        chat = build_chat_model(config=config, callbacks=[])
        response = await chat.ainvoke(
            [
                SystemMessage(content="Reply with a single word."),
                HumanMessage(content="hi"),
            ]
        )
    except Exception as exc:
        return _failure(f"{type(exc).__name__}: {exc}")

    content = getattr(response, "content", None)
    if isinstance(content, str):
        text = content.strip()
    elif isinstance(content, list):
        # Mixed-content responses (e.g. tool calls + text). Take
        # the first text part for the probe summary.
        text = ""
        for part in content:
            if isinstance(part, str):
                text = part.strip()
                break
            if isinstance(part, dict):
                maybe = part.get("text")
                if isinstance(maybe, str):
                    text = maybe.strip()
                    break
    else:
        text = str(content).strip() if content is not None else ""

    if not text:
        return _failure("empty response from provider")

    return _result(text)


# --------------------------------------------------------------------------- #
# Persistence                                                                   #
# --------------------------------------------------------------------------- #


async def _load_user_row(
    session: AsyncSession, user_id: str
) -> LLMConfigRecord | None:
    stmt = select(LLMConfigRecord).where(LLMConfigRecord.user_id == user_id)
    return (await session.exec(stmt)).first()


async def _upsert_row(
    session: AsyncSession,
    *,
    user_id: str,
    provider: str,
    model_id: str,
    base_url: str,
    api_key: str,
) -> LLMConfigRecord:
    existing = await _load_user_row(session, user_id)
    now = datetime.now(UTC)
    if existing is not None:
        existing.provider = provider
        existing.model_id = model_id
        existing.base_url = base_url
        existing.api_key = api_key
        existing.updated_at = now
        session.add(existing)
        await session.flush()
        await session.refresh(existing)
        return existing

    row = LLMConfigRecord(
        user_id=user_id,
        provider=provider,
        model_id=model_id,
        base_url=base_url,
        api_key=api_key,
    )
    session.add(row)
    await session.flush()
    await session.refresh(row)
    return row


async def upsert_user_llm_config(
    *,
    user_id: str,
    provider: str,
    model_id: str,
    base_url: str,
    api_key: str,
) -> tuple[LLMConfigRecord | None, LLMTestResult]:
    """Probe then store. Returns ``(record_or_None, test_result)``.

    On probe success: returns the persisted row and the
    ``LLMTestResult`` (with ``response`` populated).
    On probe failure or DB write failure: returns ``(None,
    LLMTestResult)`` with ``exception`` populated. The envelope
    contract is preserved in every branch.
    """
    test_result = await test_user_llm_config(
        provider=provider,
        model_id=model_id,
        base_url=base_url,
        api_key=api_key,
    )
    if test_result.get("exception") is not None:
        return None, test_result

    try:
        async with async_session_maker() as session:
            row = await _upsert_row(
                session,
                user_id=user_id,
                provider=provider,
                model_id=model_id,
                base_url=base_url,
                api_key=api_key,
            )
            await session.commit()
    except Exception as exc:
        log.warning(
            "upsert_user_llm_config: db write failed: user_id=%s exc=%s",
            user_id,
            exc,
        )
        return None, _failure(f"database error: {type(exc).__name__}: {exc}")

    return row, test_result


async def list_user_llm_configs(user_id: str) -> list[LLMConfigRecord]:
    """Return every :class:`LLMConfigRecord` belonging to ``user_id``.

    The router redacts ``api_key`` before returning. The list is
    empty when the user has no row.
    """
    async with async_session_maker() as session:
        row = await _load_user_row(session, user_id)
    return [row] if row is not None else []


# --------------------------------------------------------------------------- #
# Resolution for the review workflow                                            #
# --------------------------------------------------------------------------- #


async def resolve_active_llm_config(user_id: str) -> LLMConfig:
    """Load the user's stored :class:`LLMConfigRecord` and reconstruct.

    Raises :class:`NoActiveLLMConfigError` when the user has no
    row. The webhook's :func:`app.services.review.webhook.resolve_llm_config`
    treats that as a hard failure for the review run.
    """
    async with async_session_maker() as session:
        row = await _load_user_row(session, user_id)
    if row is None:
        raise NoActiveLLMConfigError(user_id)

    return LLMConfig(
        model=f"{row.provider}:{row.model_id}",
        api_key=row.api_key or None,
        base_url=row.base_url or None,
    )


__all__ = [
    "list_user_llm_configs",
    "resolve_active_llm_config",
    "test_user_llm_config",
    "upsert_user_llm_config",
]


# Re-export the error class for convenience, so callers can do
# ``from app.services.llm_config import NoActiveLLMConfigError``.
NoActiveLLMConfigError = NoActiveLLMConfigError
