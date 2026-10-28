"""Types for the v3 pi model-config service.

Four shapes:

- :class:`LLMConfigCtx` — the v3 primitive: provider + model + key as
  pure serializable data. No base URL: pi resolves the provider
  endpoint itself.
- :class:`PiProviderEntry` — one row of ``providers.json``: the pi
  provider id, the models.dev provider id (``None`` when models.dev
  has no equivalent), the display label, and the pi env-var hint.
- :class:`PiModelEntry` / :class:`PiModelsResult` — the model catalog
  served to the frontend. ``manualEntry=True`` (with an empty model
  list) means the provider has no models.dev mapping, so the UI must
  offer a free-text model field instead of a picker.
- :class:`PiProbeResult` — the sandbox ``pi --print`` probe outcome.
  Exactly one of ``output`` / ``error`` is non-``None``.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.utils.branded import ApiKey


class LLMConfigCtx(BaseModel):
    """Everything a pi run needs, as pure serializable data."""

    model_config = ConfigDict(frozen=True)

    provider: str = Field(min_length=1, max_length=64)
    modelId: str = Field(min_length=1, max_length=255)
    apiKey: ApiKey


class PiProviderEntry(BaseModel):
    """One row of ``providers.json`` (validated on load)."""

    model_config = ConfigDict(frozen=True)

    piProvider: str = Field(min_length=1)
    modelsDevProvider: str | None = Field(default=None)
    label: str = Field(min_length=1)
    apiKeyEnvs: list[str] = Field(default_factory=list)


class PiModelEntry(BaseModel):
    """One models.dev model projected for the picker."""

    model_config = ConfigDict(frozen=True)

    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    contextTokens: int | None = Field(default=None)
    inputCost: float | None = Field(default=None)
    outputCost: float | None = Field(default=None)


class PiModelsResult(BaseModel):
    """Model catalog for one pi provider."""

    model_config = ConfigDict(frozen=True)

    models: list[PiModelEntry] = Field(default_factory=list)
    manualEntry: bool = Field(
        default=False,
        description=(
            "True when the provider has no models.dev mapping: "
            "the UI must offer a free-text model field."
        ),
    )


class PiProbeResult(BaseModel):
    """Outcome of one sandbox ``pi --print`` probe."""

    model_config = ConfigDict(frozen=True)

    ok: bool
    output: str | None = None
    error: str | None = None


__all__ = [
    "LLMConfigCtx",
    "PiModelEntry",
    "PiModelsResult",
    "PiProbeResult",
    "PiProviderEntry",
]
