"""HTTP schemas for the per-user LLM config feature.

Two endpoints:

- ``POST /api/llm_configs`` — accept a candidate config, probe it
  via :func:`app.services.llm_config.test_user_llm_config`, and on
  success upsert the row. Always returns ``200`` with the envelope
  described below (the frontend renders the probe result directly
  from the response, so HTTP-status branching is unnecessary).
- ``GET /api/llm_configs`` — return the user's stored row(s) with
  ``api_key`` redacted. Empty list when the user has no row.

The POST response envelope:

    {
        "data": null | LLMConfigResponse,
        "success": bool,
        "error": null | "string",
        "test_result": {
            "response": null | "string",
            "exception": null | "string"
        }
    }

``data`` is non-null iff ``success`` is true. ``error`` and the
``exception`` field of ``test_result`` are both populated on
failure (the human-readable chain). The ``response`` field of
``test_result`` is populated on success.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.services.llm_config.types import LLMTestResultPublic


# --------------------------------------------------------------------------- #
# Request                                                                       #
# --------------------------------------------------------------------------- #


class CreateLLMConfigRequest(BaseModel):
    """Body of ``POST /api/llm_configs``."""

    provider: str = Field(
        min_length=1,
        max_length=64,
        description=(
            "Provider prefix accepted by "
            "``langchain.chat_models.init_chat_model`` "
            "(e.g. 'openai', 'anthropic', 'google_genai', "
            "'openrouter')."
        ),
    )
    model_id: str = Field(
        min_length=1,
        max_length=255,
        description="Model identifier (the part after ':' in LLM_MODEL).",
    )
    base_url: str = Field(
        min_length=1,
        max_length=1024,
        description=(
            "Base URL for the chat model. Required when proxying "
            "through an OpenAI-compatible gateway (Cloudflare AI "
            "Gateway, OpenCode Zen, OpenRouter, Ollama, etc.)."
        ),
    )
    api_key: str = Field(
        min_length=1,
        max_length=512,
        description="API key for the active provider.",
    )


# --------------------------------------------------------------------------- #
# Response — record shape (api_key always redacted)                             #
# --------------------------------------------------------------------------- #


class LLMConfigResponse(BaseModel):
    """Stored config, returned to the client with ``api_key`` omitted."""

    id: UUID
    user_id: str
    provider: str
    model_id: str
    base_url: str
    created_at: datetime
    updated_at: datetime


def to_llm_config_response(row) -> LLMConfigResponse:
    """Map a :class:`LLMConfigRecord` ORM row to its public response.

    Strips ``api_key`` before returning. Centralising the
    redaction here keeps the router free of PII surface and
    makes it impossible to leak the key by accident.
    """
    return LLMConfigResponse(
        id=UUID(str(row.id)),
        user_id=row.user_id,
        provider=row.provider,
        model_id=row.model_id,
        base_url=row.base_url,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


# --------------------------------------------------------------------------- #
# Response — POST envelope                                                      #
# --------------------------------------------------------------------------- #


class LLMConfigUpsertResponse(BaseModel):
    """Body of the ``POST /api/llm_configs`` response."""

    data: LLMConfigResponse | None = Field(
        default=None,
        description=(
            "Persisted config on success; ``None`` on failure. The "
            "client uses ``data is not None`` as the canonical "
            "success signal."
        ),
    )
    success: bool = Field(
        description="``True`` iff ``data`` is non-null.",
    )
    error: str | None = Field(
        default=None,
        description=(
            "Human-readable error string on failure; ``None`` on "
            "success. Mirrors ``test_result.exception`` for "
            "convenience."
        ),
    )
    test_result: LLMTestResultPublic = Field(
        description=(
            "The raw probe outcome. ``response`` is populated on "
            "success; ``exception`` is populated on failure. The "
            "client can render either branch directly."
        ),
    )


__all__ = [
    "CreateLLMConfigRequest",
    "LLMConfigResponse",
    "LLMConfigUpsertResponse",
    "to_llm_config_response",
]
