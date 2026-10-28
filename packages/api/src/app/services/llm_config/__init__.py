"""V3 pi model-config service (``app.services.llm_config``).

Owns the pi provider map (``providers.json``), the live models.dev
model catalog, the sandbox ``pi --print`` probe, and the per-user
``llmconfig`` row. Isolated from the v2 ``app.services.llm`` package:
nothing here imports it.
"""

from app.services.llm_config.errors import LLMConfigStoreError
from app.services.llm_config.service import (
    findProviderEntry,
    getPiLLMConfig,
    getPiLLMConfigWithDecryptedKey,
    listPiModels,
    listPiProviders,
    loadProviderMap,
    runPiProbe,
    savePiLLMConfig,
)
from app.services.llm_config.types import (
    LLMConfigCtx,
    PiModelEntry,
    PiModelsResult,
    PiProbeResult,
    PiProviderEntry,
)

__all__ = [
    "LLMConfigCtx",
    "LLMConfigStoreError",
    "PiModelEntry",
    "PiModelsResult",
    "PiProbeResult",
    "PiProviderEntry",
    "findProviderEntry",
    "getPiLLMConfig",
    "getPiLLMConfigWithDecryptedKey",
    "listPiModels",
    "listPiProviders",
    "loadProviderMap",
    "runPiProbe",
    "savePiLLMConfig",
]
