"""HTTP schemas for the v3 pi model-config feature.

Three endpoints:

- ``GET /api/llm-config/providers`` — the pi provider map.
- ``GET /api/llm-config/models?provider=`` — tool-capable models for
  one provider (live models.dev), or ``manualEntry=True``.
- ``GET /api/llm-config/`` — the user's stored row (``api_key``
  redacted), or ``None``.
- ``POST /api/llm-config/`` — test the candidate in a sandbox, then
  save on success. Always returns ``200`` with the envelope below.

The POST response envelope:

    {
        "data": null | PiLLMConfigResponse,
        "success": bool,
        "error": null | "string",
        "test_result": {
            "response": null | "string",
            "exception": null | "string"
        }
    }
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.models.pi_llm_config import LLMConfig
from app.services.llm_config.types import PiModelEntry


# --------------------------------------------------------------------------- #
# Request                                                                       #
# --------------------------------------------------------------------------- #


class CreatePiLLMConfigRequest(BaseModel):
    """Body of ``POST /api/llm-config/``."""

    provider: str = Field(
        min_length=1,
        max_length=64,
        description="Pi provider id (e.g. 'anthropic', 'fireworks').",
    )
    model_id: str = Field(
        min_length=1,
        max_length=255,
        description="Model id accepted by pi for the provider.",
    )
    api_key: str = Field(
        min_length=1,
        max_length=512,
        description="API key for the provider.",
    )


# --------------------------------------------------------------------------- #
# Response — catalog                                                            #
# --------------------------------------------------------------------------- #


class PiModelsResponse(BaseModel):
    """Body of ``GET /api/llm-config/models``."""

    provider: str = Field(description="The requested pi provider id.")
    models: list[PiModelEntry] = Field(default_factory=list)
    manualEntry: bool = Field(
        default=False,
        description=(
            "True when the provider has no models.dev mapping: "
            "the UI must offer a free-text model field."
        ),
    )


# --------------------------------------------------------------------------- #
# Response — record shape (api_key always redacted)                             #
# --------------------------------------------------------------------------- #


class PiLLMConfigResponse(BaseModel):
    """Stored pi config, returned to the client with ``api_key`` omitted."""

    id: UUID
    user_id: str
    provider: str
    model_id: str
    created_at: datetime
    updated_at: datetime


def to_pi_llm_config_response(record: LLMConfig) -> PiLLMConfigResponse:
    """Map an :class:`LLMConfig` ORM row to its public response."""
    return PiLLMConfigResponse(
        id=UUID(str(record.id)),
        user_id=record.user_id,
        provider=record.provider,
        model_id=record.model_id,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


# --------------------------------------------------------------------------- #
# Response — POST envelope                                                      #
# --------------------------------------------------------------------------- #


class PiTestResultPublic(BaseModel):
    """Pydantic mirror of the probe outcome for the API surface."""

    response: str | None = None
    exception: str | None = None


class PiLLMConfigUpsertResponse(BaseModel):
    """Body of the ``POST /api/llm-config/`` response."""

    data: PiLLMConfigResponse | None = Field(
        default=None,
        description="Persisted config on success; ``None`` on failure.",
    )
    success: bool = Field(
        description="``True`` iff ``data`` is non-null.",
    )
    error: str | None = Field(
        default=None,
        description="Human-readable error string on failure; ``None`` on success.",
    )
    test_result: PiTestResultPublic = Field(
        description="The raw probe outcome.",
    )


__all__ = [
    "CreatePiLLMConfigRequest",
    "PiLLMConfigResponse",
    "PiLLMConfigUpsertResponse",
    "PiModelsResponse",
    "PiTestResultPublic",
    "to_pi_llm_config_response",
]
