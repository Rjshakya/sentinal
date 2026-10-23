"""V3 pi model-config routes.

- ``GET /llm-config/providers`` — the pi provider map.
- ``GET /llm-config/models?provider=`` — tool-capable models for one
  provider (live models.dev), or ``manualEntry=True`` when the
  provider has no models.dev mapping.
- ``GET /llm-config/`` — the user's stored row with ``api_key``
  redacted, or ``None``.
- ``POST /llm-config/`` — test the candidate in an ephemeral sandbox
  (``pi --print``), then save on success. Always returns ``200``
  with the :class:`PiLLMConfigUpsertResponse` envelope.

All routes are protected by :class:`app.core.middleware.AuthMiddleware`
(see ``AuthMiddleware.PROTECTED_PREFIXES``).
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Request
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.db import get_session
from app.routers.schemas.pi_llm_config import (
    CreatePiLLMConfigRequest,
    PiLLMConfigResponse,
    PiLLMConfigUpsertResponse,
    PiModelsResponse,
    PiTestResultPublic,
    to_pi_llm_config_response,
)
from app.services.llm_config import (
    LLMConfigStoreError,
    findProviderEntry,
    getPiLLMConfig,
    listPiModels,
    listPiProviders,
    runPiProbe,
    savePiLLMConfig,
)
from app.services.llm_config.types import LLMConfigCtx, PiProviderEntry
from app.utils.branded import ApiKey, UserId

log = logging.getLogger(__name__)

router = APIRouter(prefix="/llm-config", tags=["pi_llm_config"])


@router.get("/providers", response_model=list[PiProviderEntry])
async def list_providers() -> list[PiProviderEntry]:
    """Return the pi provider map."""
    entries = listPiProviders()
    if isinstance(entries, LLMConfigStoreError):
        log.warning("pi_llm_config: provider map failed: %s", entries.message)
        return []
    return entries


@router.get("/models", response_model=PiModelsResponse)
async def list_models(provider: str) -> PiModelsResponse:
    """Return tool-capable models for one pi provider."""
    result = await listPiModels(piProvider=provider)
    if isinstance(result, LLMConfigStoreError):
        log.info(
            "pi_llm_config: models failed: provider=%s error=%s",
            provider,
            result.message,
        )
        return PiModelsResponse(provider=provider, models=[], manualEntry=True)
    return PiModelsResponse(
        provider=provider, models=result.models, manualEntry=result.manualEntry
    )


@router.get("/", response_model=PiLLMConfigResponse | None)
async def get_my_pi_llm_config(
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> PiLLMConfigResponse | None:
    """Return the user's stored pi config with ``api_key`` redacted."""
    user_id: str = request.state.user_id
    row = await getPiLLMConfig(session, UserId(user_id))
    if row is None:
        return None
    return to_pi_llm_config_response(row)


@router.post("/", response_model=PiLLMConfigUpsertResponse)
async def create_or_replace_my_pi_llm_config(
    request: Request,
    body: CreatePiLLMConfigRequest,
    session: AsyncSession = Depends(get_session),
) -> PiLLMConfigUpsertResponse:
    """Test the candidate in a sandbox, then store it on success."""
    user_id: str = request.state.user_id

    log.info(
        "pi_llm_config: upsert start: user_id=%s provider=%s model_id=%s",
        user_id,
        body.provider,
        body.model_id,
    )

    entries = listPiProviders()
    if isinstance(entries, LLMConfigStoreError):
        return PiLLMConfigUpsertResponse(
            data=None,
            success=False,
            error=entries.message,
            test_result=PiTestResultPublic(response=None, exception=entries.message),
        )
    entry = findProviderEntry(entries, body.provider)
    if entry is None:
        error = f"unknown provider: {body.provider!r}"
        return PiLLMConfigUpsertResponse(
            data=None,
            success=False,
            error=error,
            test_result=PiTestResultPublic(response=None, exception=error),
        )
    if not entry.apiKeyEnvs:
        error = (
            f"provider {body.provider!r} needs an OAuth sign-in; "
            "an API key is not supported"
        )
        log.info("pi_llm_config: upsert rejected (oauth-only): user_id=%s", user_id)
        return PiLLMConfigUpsertResponse(
            data=None,
            success=False,
            error=error,
            test_result=PiTestResultPublic(response=None, exception=error),
        )

    ctx = LLMConfigCtx(
        provider=body.provider,
        modelId=body.model_id,
        apiKey=ApiKey(body.api_key),
    )
    probe = await runPiProbe(ctx=ctx, userId=UserId(user_id))
    if not probe.ok:
        log.info(
            "pi_llm_config: upsert failed (probe): user_id=%s error=%s",
            user_id,
            probe.error,
        )
        return PiLLMConfigUpsertResponse(
            data=None,
            success=False,
            error=probe.error,
            test_result=PiTestResultPublic(response=None, exception=probe.error),
        )

    record = await savePiLLMConfig(session, userId=UserId(user_id), ctx=ctx)
    if isinstance(record, LLMConfigStoreError):
        log.info(
            "pi_llm_config: upsert failed (db): user_id=%s error=%s",
            user_id,
            record.message,
        )
        return PiLLMConfigUpsertResponse(
            data=None,
            success=False,
            error=record.message,
            test_result=PiTestResultPublic(
                response=probe.output, exception=record.message
            ),
        )

    try:
        await session.commit()
    except Exception as exc:
        error = f"database error: {type(exc).__name__}: {exc}"
        log.info("pi_llm_config: upsert failed (commit): user_id=%s", user_id)
        return PiLLMConfigUpsertResponse(
            data=None,
            success=False,
            error=error,
            test_result=PiTestResultPublic(response=probe.output, exception=error),
        )

    log.info(
        "pi_llm_config: upsert ok: user_id=%s provider=%s model_id=%s",
        user_id,
        record.provider,
        record.model_id,
    )
    return PiLLMConfigUpsertResponse(
        data=to_pi_llm_config_response(record),
        success=True,
        error=None,
        test_result=PiTestResultPublic(response=probe.output, exception=None),
    )


__all__ = [
    "create_or_replace_my_pi_llm_config",
    "get_my_pi_llm_config",
    "list_models",
    "list_providers",
    "router",
]
