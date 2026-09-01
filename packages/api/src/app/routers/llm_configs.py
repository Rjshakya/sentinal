"""Per-user LLM config routes.

- ``POST /api/llm_config/`` — test-and-create. Always returns
  ``200`` with the :class:`LLMConfigUpsertResponse` envelope so
  the frontend has a single shape to render regardless of pass /
  fail. The probe runs **before** the DB write; on success the
  row is upserted (one config per user).
- ``POST /api/llm_config/test`` — test-only. Runs the same probe
  as the upsert endpoint but never writes. Returns the
  :class:`LLMConfigTestResponse` envelope (same shape, no ``data``).
- ``GET /api/llm_config/`` — list the user's stored config with
  ``api_key`` redacted. Empty list when the user has none.

All routes are protected by :class:`app.core.middleware.AuthMiddleware`
(see :data:`AuthMiddleware.PROTECTED_PREFIXES`).
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Request
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.db import get_session
from app.schemas.llm_config import (
    CreateLLMConfigRequest,
    LLMConfigResponse,
    LLMConfigTestResponse,
    LLMConfigUpsertResponse,
    to_llm_config_response,
)
from app.services.llm.config import (
    LLMConfigStoreError,
    listUserLLMConfigs,
    saveUserLLMConfig,
    testLLMConfig,
)
from app.services.llm.config.types import LLMConfigTestResultPublic
from app.utils.branded import UserId

log = logging.getLogger(__name__)

router = APIRouter(prefix="/llm_config", tags=["llm_configs"])


@router.post("/", response_model=LLMConfigUpsertResponse)
async def create_or_replace_my_llm_config(
    request: Request,
    body: CreateLLMConfigRequest,
    session: AsyncSession = Depends(get_session),
) -> LLMConfigUpsertResponse:
    """Test the supplied config, then store it on success.

    Returns the standard envelope so the frontend can render the
    probe's outcome directly. HTTP status is always ``200``; the
    ``success`` / ``error`` / ``test_result`` fields are the
    pass/fail signal.
    """
    user_id: str = request.state.user_id

    log.info(
        "llm_configs: upsert start: user_id=%s provider=%s model_id=%s",
        user_id,
        body.provider,
        body.model_id,
    )

    test_result = await testLLMConfig(
        provider=body.provider,
        modelId=body.model_id,
        baseUrl=body.base_url,
        apiKey=body.api_key,
    )
    public_test = LLMConfigTestResultPublic(
        response=test_result.get("response"),
        exception=test_result.get("exception"),
    )

    if public_test.exception is not None:
        log.info(
            "llm_configs: upsert failed (probe): user_id=%s exception=%s",
            user_id,
            public_test.exception,
        )
        return LLMConfigUpsertResponse(
            data=None,
            success=False,
            error=public_test.exception,
            test_result=public_test,
        )

    record = await saveUserLLMConfig(
        session,
        userId=UserId(user_id),
        provider=body.provider,
        modelId=body.model_id,
        baseUrl=body.base_url,
        apiKey=body.api_key,
    )
    if isinstance(record, LLMConfigStoreError):
        log.info(
            "llm_configs: upsert failed (db): user_id=%s exception=%s",
            user_id,
            record.message,
        )
        return LLMConfigUpsertResponse(
            data=None,
            success=False,
            error=record.message,
            test_result=public_test,
        )

    try:
        await session.commit()
    except Exception as exc:
        log.info(
            "llm_configs: upsert failed (commit): user_id=%s exc=%s",
            user_id,
            exc,
        )
        return LLMConfigUpsertResponse(
            data=None,
            success=False,
            error=f"database error: {type(exc).__name__}: {exc}",
            test_result=public_test,
        )

    log.info(
        "llm_configs: upsert ok: user_id=%s config_id=%s provider=%s model_id=%s",
        user_id,
        record.id,
        record.provider,
        record.model_id,
    )
    return LLMConfigUpsertResponse(
        data=to_llm_config_response(record),
        success=True,
        error=None,
        test_result=public_test,
    )


@router.post("/test", response_model=LLMConfigTestResponse)
async def test_my_llm_config(
    request: Request,
    body: CreateLLMConfigRequest,
) -> LLMConfigTestResponse:
    """Probe a candidate config without persisting it.

    Mirrors the probe run inside the upsert endpoint. The service
    layer promises :func:`testLLMConfig` never raises, so
    the only branch here is the successful / failed probe result.
    The frontend renders the probe outcome directly from the
    response — no HTTP-status branching required.
    """
    user_id: str = request.state.user_id

    log.info(
        "llm_configs: test start: user_id=%s provider=%s model_id=%s",
        user_id,
        body.provider,
        body.model_id,
    )

    test_result = await testLLMConfig(
        provider=body.provider,
        modelId=body.model_id,
        baseUrl=body.base_url,
        apiKey=body.api_key,
    )
    public_test = LLMConfigTestResultPublic(
        response=test_result.get("response"),
        exception=test_result.get("exception"),
    )

    if public_test.exception is not None:
        log.info(
            "llm_configs: test failed: user_id=%s exception=%s",
            user_id,
            public_test.exception,
        )
    else:
        log.info(
            "llm_configs: test ok: user_id=%s provider=%s model_id=%s",
            user_id,
            body.provider,
            body.model_id,
        )

    return LLMConfigTestResponse(
        success=public_test.exception is None,
        error=public_test.exception,
        test_result=public_test,
    )


@router.get("/", response_model=list[LLMConfigResponse])
async def list_my_llm_config(
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> list[LLMConfigResponse]:
    """Return the user's stored config with ``api_key`` redacted.

    Empty list when the user has no row. One element at most —
    one config per user.
    """
    user_id: str = request.state.user_id
    rows = await listUserLLMConfigs(session, UserId(user_id))
    return [to_llm_config_response(row) for row in rows]


__all__ = [
    "create_or_replace_my_llm_config",
    "list_my_llm_config",
    "router",
    "test_my_llm_config",
]