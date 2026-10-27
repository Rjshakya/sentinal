"""V3 pi model-config service: catalog + sandbox probe + storage.

Entry points (all async except the provider-map loader):

- :func:`listPiProviders` — the ``providers.json`` map, validated.
- :func:`listPiModels` — live models.dev lookup for one pi provider,
  filtered to tool-capable models. ``manualEntry=True`` when the
  provider has no models.dev mapping.
- :func:`runPiProbe` — spin up an ephemeral E2B sandbox and run
  ``pi --provider … --model … --api-key … -p "Hi there?"``.
  **Never raises**; failures fold into :class:`PiProbeResult`.
  The sandbox is always destroyed (best-effort).
- :func:`savePiLLMConfig` — upsert the user's ``llmconfig`` row (one
  row per user). Takes an already-encrypted key: plaintext never
  reaches the table. Returns ``LLMConfig | LLMConfigStoreError``.
- :func:`getPiLLMConfig` — load the user's stored row, if any.
- :func:`getDecryptedPiKey` — the stored provider key, decrypted for
  use. Legacy plaintext rows fall back to direct use.

The DB session is owned by the caller; committing is the caller's
job too. No logging here (edge logs). Error contract: expected
failures are values, never exceptions.
"""

from __future__ import annotations

import asyncio
import json
import shlex
import urllib.request
from pathlib import Path
from typing import Any, TypedDict, cast

from deepagents.backends.protocol import ExecuteResponse
from deepagents.backends.sandbox import BaseSandbox
from sqlmodel.ext.asyncio.session import AsyncSession
from typing_extensions import Protocol

from app.core.config import settings
from app.models.pi_llm_config import LLMConfig
from app.repositories.pi_llm_config import PiLLMConfigRepository
from app.services.api_key_crypto.errors import ApiKeyDecryptError
from app.services.api_key_crypto.service import ApiKeyCipher
from app.services.api_key_crypto.types import EncryptedApiKey
from app.services.llm_config.errors import LLMConfigStoreError
from app.services.llm_config.types import (
    LLMConfigCtx,
    PiModelEntry,
    PiModelsResult,
    PiProbeResult,
    PiProviderEntry,
)
from app.services.sandbox.errors import SandboxProviderError
from app.services.sandbox.service import createSandboxCtx, getProvider
from app.services.sandbox.types import ProviderId, SandboxCtx
from app.utils.branded import ApiKey, RepoId, UserId
from app.utils.branded import SanboxProviderApiKey

_MODELS_DEV_API_URL = "https://models.dev/api.json"
_MODELS_DEV_TIMEOUT_S = 30
_PROBE_TIMEOUT_S = 90
_PROBE_MESSAGE = "Hi there?"
_PROBE_OUTPUT_CHARS = 500

_PROVIDERS_FILE = Path(__file__).with_name("providers.json")
_PROVIDERS_CACHE: list[PiProviderEntry] | None = None


# --------------------------------------------------------------------------- #
# models.dev wire shapes                                                        #
# --------------------------------------------------------------------------- #


class _ModelsDevCost(TypedDict, total=False):
    """Pricing block of one models.dev model entry."""

    input: float
    output: float


class _ModelsDevLimit(TypedDict, total=False):
    """Limit block of one models.dev model entry."""

    context: int


class _ModelsDevModel(TypedDict, total=False):
    """One models.dev model entry (only the fields we project)."""

    name: str
    tool_call: bool
    limit: _ModelsDevLimit
    cost: _ModelsDevCost


class _ModelsDevProvider(TypedDict, total=False):
    """One models.dev provider entry (only the fields we project)."""

    models: dict[str, _ModelsDevModel]


# --------------------------------------------------------------------------- #
# Provider map                                                                  #
# --------------------------------------------------------------------------- #


def loadProviderMap() -> list[PiProviderEntry] | LLMConfigStoreError:
    """Load and validate ``providers.json`` (cached after first load)."""
    global _PROVIDERS_CACHE
    if _PROVIDERS_CACHE is not None:
        return _PROVIDERS_CACHE
    try:
        raw = json.loads(_PROVIDERS_FILE.read_text(encoding="utf-8"))
    except Exception as exc:
        return LLMConfigStoreError(
            message=f"cannot read provider map: {type(exc).__name__}: {exc}"
        )
    if not isinstance(raw, list):
        return LLMConfigStoreError(message="provider map is not a JSON list")
    try:
        entries = [PiProviderEntry.model_validate(item) for item in raw]
    except Exception as exc:
        return LLMConfigStoreError(
            message=f"invalid provider map: {type(exc).__name__}: {exc}"
        )
    seen: set[str] = set()
    for entry in entries:
        if entry.piProvider in seen:
            return LLMConfigStoreError(
                message=f"duplicate provider in map: {entry.piProvider!r}"
            )
        seen.add(entry.piProvider)
    _PROVIDERS_CACHE = entries
    return entries


def listPiProviders() -> list[PiProviderEntry] | LLMConfigStoreError:
    """Return the validated pi provider map."""
    return loadProviderMap()


def findProviderEntry(
    entries: list[PiProviderEntry], piProvider: str
) -> PiProviderEntry | None:
    """Return the map entry for ``piProvider``, if any."""
    for entry in entries:
        if entry.piProvider == piProvider:
            return entry
    return None


# --------------------------------------------------------------------------- #
# Model catalog (live models.dev)                                               #
# --------------------------------------------------------------------------- #


def _downloadCatalog(*, timeoutS: int) -> dict[str, Any]:
    """Download the models.dev catalog (blocking; run in a thread)."""
    request = urllib.request.Request(
        _MODELS_DEV_API_URL,
        headers={"User-Agent": "sentinel-pi-config", "Accept": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=timeoutS) as response:
        payload: Any = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("models.dev catalog is not a JSON object")
    return payload


def _toPiModelEntry(modelId: str, raw: Any) -> PiModelEntry | None:
    """Project one models.dev model entry; ``None`` when unusable."""
    if not isinstance(raw, dict):
        return None
    name = raw.get("name")
    if not isinstance(name, str) or not name:
        return None
    contextTokens: int | None = None
    limit = raw.get("limit")
    if isinstance(limit, dict):
        context = limit.get("context")
        if isinstance(context, bool):
            contextTokens = None
        elif isinstance(context, int):
            contextTokens = context
    inputCost: float | None = None
    outputCost: float | None = None
    cost = raw.get("cost")
    if isinstance(cost, dict):
        price_in = cost.get("input")
        price_out = cost.get("output")
        if isinstance(price_in, bool):
            inputCost = None
        elif isinstance(price_in, (int, float)):
            inputCost = float(price_in)
        if isinstance(price_out, bool):
            outputCost = None
        elif isinstance(price_out, (int, float)):
            outputCost = float(price_out)
    return PiModelEntry(
        id=modelId,
        name=name,
        contextTokens=contextTokens,
        inputCost=inputCost,
        outputCost=outputCost,
    )


async def listPiModels(*, piProvider: str) -> PiModelsResult | LLMConfigStoreError:
    """List tool-capable models for one pi provider via models.dev.

    Returns ``manualEntry=True`` with an empty list when the provider
    has no models.dev mapping (the UI must offer a free-text field).
    Never raises.
    """
    entries = loadProviderMap()
    if isinstance(entries, LLMConfigStoreError):
        return entries
    entry = findProviderEntry(entries, piProvider)
    if entry is None:
        return LLMConfigStoreError(message=f"unknown provider: {piProvider!r}")
    if entry.modelsDevProvider is None:
        return PiModelsResult(models=[], manualEntry=True)
    try:
        catalog = await asyncio.to_thread(
            _downloadCatalog, timeoutS=_MODELS_DEV_TIMEOUT_S
        )
    except Exception as exc:
        return LLMConfigStoreError(
            message=f"models.dev lookup failed: {type(exc).__name__}: {exc}"
        )
    providerRaw = catalog.get(entry.modelsDevProvider)
    if not isinstance(providerRaw, dict):
        return LLMConfigStoreError(
            message=f"models.dev has no provider {entry.modelsDevProvider!r}"
        )
    modelsRaw = providerRaw.get("models")
    if not isinstance(modelsRaw, dict):
        return LLMConfigStoreError(
            message=f"models.dev provider {entry.modelsDevProvider!r} has no models"
        )
    models: list[PiModelEntry] = []
    for modelId, modelRaw in modelsRaw.items():
        if not isinstance(modelRaw, dict):
            continue
        if modelRaw.get("tool_call") is not True:
            continue
        projected = _toPiModelEntry(modelId, modelRaw)
        if projected is not None:
            models.append(projected)
    models.sort(key=lambda model: model.id)
    return PiModelsResult(models=models, manualEntry=False)


# --------------------------------------------------------------------------- #
# Sandbox probe                                                                 #
# --------------------------------------------------------------------------- #


class _ExecBackend(Protocol):
    """The async exec surface the probe runs on."""

    async def aexecute(
        self, command: str, *, timeout: int | None = None
    ) -> ExecuteResponse: ...


def _buildProbeCommand(ctx: LLMConfigCtx) -> str:
    """Build the ``pi --print`` probe command (key passed via flag)."""
    return (
        "pi"
        f" --provider {shlex.quote(ctx.provider)}"
        f" --model {shlex.quote(ctx.modelId)}"
        f" --api-key {shlex.quote(str(ctx.apiKey))}"
        f" -p {shlex.quote(_PROBE_MESSAGE)}"
    )


def _redact(output: str, apiKey: str) -> str:
    """Trim the probe output tail and scrub the key, defensively."""
    cleaned = (output or "").strip()
    if apiKey:
        cleaned = cleaned.replace(apiKey, "***")
    return cleaned[:_PROBE_OUTPUT_CHARS]


async def runPiProbe(*, ctx: LLMConfigCtx, userId: UserId) -> PiProbeResult:
    """Run the ``pi --print`` probe in an ephemeral sandbox.

    Creates a fresh sandbox, runs one command, destroys the sandbox.
    Never raises: every failure mode folds into :class:`PiProbeResult`.
    The API key never leaves the sandbox command and is scrubbed from
    any returned output.
    """
    providerId = settings.sandbox_provider
    if providerId != "e2b":
        return PiProbeResult(
            ok=False,
            output=None,
            error=f"unsupported sandbox provider: {providerId!r}",
        )
    sandboxKey = settings.e2b_api_key
    if not sandboxKey:
        return PiProbeResult(
            ok=False, output=None, error="sandbox provider key is not configured"
        )
    sandboxCtx = createSandboxCtx(
        userId=userId,
        repoId=RepoId("pi-probe"),
        repoName="pi-probe",
        providerId=cast(ProviderId, providerId),
        apiKey=SanboxProviderApiKey(sandboxKey),
        sandboxName="pi-probe-sandbox",
        rootPath="/home/user",
    )
    try:
        provider = getProvider(sandboxCtx.providerId)
    except Exception as exc:
        return PiProbeResult(
            ok=False,
            output=None,
            error=f"unknown sandbox provider: {type(exc).__name__}",
        )
    try:
        backend = await provider(ctx=sandboxCtx).create()
    except Exception as exc:
        return PiProbeResult(
            ok=False,
            output=None,
            error=f"sandbox create failed: {type(exc).__name__}: {exc}",
        )
    if isinstance(backend, SandboxProviderError):
        return PiProbeResult(
            ok=False, output=None, error=f"sandbox error: {backend.message}"
        )
    execBackend = cast(_ExecBackend, cast(BaseSandbox, backend))
    try:
        try:
            ran = await execBackend.aexecute(
                _buildProbeCommand(ctx), timeout=_PROBE_TIMEOUT_S
            )
        except Exception as exc:
            print(exc)
            return PiProbeResult(
                ok=False,
                output=None,
                error=f"probe command failed: {type(exc).__name__}: {exc}",
            )
        redacted = _redact(ran.output, str(ctx.apiKey))
        if ran.exit_code != 0:
            detail = redacted or f"exit code {ran.exit_code}"
            return PiProbeResult(
                ok=False, output=None, error=f"pi exited {ran.exit_code}: {detail}"
            )
        return PiProbeResult(ok=True, output=redacted or "(empty reply)", error=None)
    finally:
        try:
            await provider(ctx=sandboxCtx).kill()
        except Exception:
            pass


# --------------------------------------------------------------------------- #
# Storage                                                                       #
# --------------------------------------------------------------------------- #


async def savePiLLMConfig(
    session: AsyncSession,
    *,
    userId: UserId,
    provider: str,
    modelId: str,
    encryptedKey: EncryptedApiKey,
) -> LLMConfig | LLMConfigStoreError:
    """Upsert the user's ``llmconfig`` row; never raises.

    The key arrives already encrypted (edge encrypts via
    :class:`ApiKeyCipher` before calling) — plaintext never reaches
    the table. One row per user: an existing row is replaced. The
    caller owns the session and the commit.
    """
    from datetime import UTC, datetime

    repo = PiLLMConfigRepository(session=session)
    try:
        existing = await repo.find_by_user(userId)
        if existing is not None:
            existing.provider = provider
            existing.model_id = modelId
            existing.api_key = str(encryptedKey)
            existing.updated_at = datetime.now(UTC)
            await repo.add(existing)
            await session.flush()
            await session.refresh(existing)
            return existing

        row = LLMConfig(
            user_id=userId,
            provider=provider,
            model_id=modelId,
            api_key=str(encryptedKey),
        )
        await repo.add(row)
        await session.flush()
        await session.refresh(row)
        return row
    except Exception as exc:
        return LLMConfigStoreError(
            message=f"database error: {type(exc).__name__}: {exc}"
        )


async def getPiLLMConfig(
    session: AsyncSession,
    userId: UserId,
) -> LLMConfig | None:
    """Return the user's stored :class:`LLMConfig`, if any."""
    repo = PiLLMConfigRepository(session=session)
    return await repo.find_by_user(userId)


async def getDecryptedPiKey(
    session: AsyncSession,
    *,
    userId: UserId,
    cipher: ApiKeyCipher,
) -> ApiKey | ApiKeyDecryptError | LLMConfigStoreError:
    """Return the user's stored provider key, decrypted for use.

    Legacy plaintext rows (written before at-rest encryption) fall
    back to direct use — they re-encrypt opportunistically on the
    next save. Never raises.
    """
    try:
        row = await PiLLMConfigRepository(session=session).find_by_user(userId)
    except Exception as exc:
        return LLMConfigStoreError(
            message=f"database error: {type(exc).__name__}: {exc}"
        )
    if row is None or not row.api_key:
        return LLMConfigStoreError(message=f"no pi config for user {userId!r}")
    decrypted = cipher.decrypt(EncryptedApiKey(row.api_key))
    if isinstance(decrypted, ApiKeyDecryptError):
        return ApiKey(row.api_key)
    return decrypted


__all__ = [
    "findProviderEntry",
    "getDecryptedPiKey",
    "getPiLLMConfig",
    "listPiModels",
    "listPiProviders",
    "loadProviderMap",
    "runPiProbe",
    "savePiLLMConfig",
]
