"""Unit tests for the v3 pi model-config catalog (no network, no sandbox).

Covers the provider map contract and the offline branches of
:func:`app.services.llm_config.service.listPiModels` (unknown
provider, manual-entry provider). The live models.dev branch is
exercised manually, not here.

Run: cd packages/api && uv run pytest tests/llm_config -v
"""

from __future__ import annotations

from app.services.llm_config.errors import LLMConfigStoreError
from app.services.llm_config.service import (
    findProviderEntry,
    listPiModels,
    listPiProviders,
)
from app.services.llm_config.types import PiModelsResult, PiProviderEntry


def test_provider_map_has_42_unique_entries() -> None:
    entries = listPiProviders()
    assert isinstance(entries, list)
    assert len(entries) == 42
    ids = [entry.piProvider for entry in entries]
    assert len(set(ids)) == 42


def test_provider_map_mismatch_entries() -> None:
    entries = listPiProviders()
    assert isinstance(entries, list)
    fireworks = findProviderEntry(entries, "fireworks")
    assert isinstance(fireworks, PiProviderEntry)
    assert fireworks.modelsDevProvider == "fireworks-ai"
    together = findProviderEntry(entries, "together")
    assert isinstance(together, PiProviderEntry)
    assert together.modelsDevProvider == "togetherai"


def test_provider_map_oauth_only_entry() -> None:
    entries = listPiProviders()
    assert isinstance(entries, list)
    codex = findProviderEntry(entries, "openai-codex")
    assert isinstance(codex, PiProviderEntry)
    assert codex.apiKeyEnvs == []
    assert findProviderEntry(entries, "no-such-provider") is None


async def test_list_models_unknown_provider_is_error() -> None:
    result = await listPiModels(piProvider="no-such-provider")
    assert isinstance(result, LLMConfigStoreError)
    assert "unknown provider" in result.message


async def test_list_models_unmapped_provider_needs_manual_entry() -> None:
    result = await listPiModels(piProvider="radius")
    assert isinstance(result, PiModelsResult)
    assert result.manualEntry is True
    assert result.models == []
