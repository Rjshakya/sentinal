"""Tracing service: Langfuse handler + attributes + flush.

Entry points (camelCase, matching the package convention):

- :func:`isTracingConfigured` — True when Langfuse keys are set.
- :func:`traceSessionId` — deterministic per-run session id from run ids.
- :func:`createTraceCallbacks` — one Langfuse ``CallbackHandler`` for an
  agent ``ainvoke`` call, or ``[]`` when tracing is disabled.
- :func:`buildAgentConfig` — the ``config`` dict for ``ainvoke`` calls
  (run name + tags + metadata + callbacks).
- :func:`propagateReviewAttrs` — context manager setting user/session
  attributes on all nested observations.
- :func:`flushTraces` — best-effort flush for short-lived processes
  (scripts, Lambda handlers). Never raises.

Error contract: **no function in this module raises.** Langfuse client
construction and flush are best-effort; a missing/invalid config simply
yields no callbacks and no attributes. Services keep their
error-as-value contract — tracing never changes a return value.

Credentials: the Langfuse keys live in settings (process env /
Secrets Manager) and are read by the Langfuse client itself. They are
never carried on :class:`ReviewTraceCtx` and never enter span
metadata.

Naming convention: this package intentionally uses **camelCase**
identifiers — the same convention as :mod:`app.services.github`,
:mod:`app.services.llm`, and :mod:`app.services.sandbox`.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.runnables import RunnableConfig

from app.core.config import settings
from app.services.tracing.types import ReviewTraceCtx


def isTracingConfigured() -> bool:
    """True when Langfuse keys are set (traces actually export)."""
    return settings.langfuse_configured


def traceSessionId(
    *, userId: str, repoId: str, prNumber: int, headSha: str
) -> str:
    """Build the stable per-run session id from run ids.

    Pure: deterministic, no I/O. All lanes of a run (planner + file
    lanes + extractor + summary) share it, so they group into one
    Langfuse session without threading execution names through durable
    step inputs. Only the short SHA rides along (low-cardinality ids
    stay in metadata).
    """
    short_sha: str = headSha[:7] if len(headSha) >= 7 else headSha
    return f"review:{userId}:{repoId}:{prNumber}:{short_sha}"


def createTraceCallbacks() -> list[BaseCallbackHandler]:
    """Create the Langfuse handler for one agent call.

    Returns ``[]`` when tracing is disabled or the handler fails to
    build, so callers can always spread the result into ``config``
    without branching. Never raises.
    """
    if not settings.langfuse_configured:
        return []
    try:
        from langfuse.langchain import CallbackHandler

        handler: BaseCallbackHandler = CallbackHandler()
        return [handler]
    except Exception:
        return []


def buildAgentConfig(
    *,
    ctx: ReviewTraceCtx,
    runName: str,
    lane: str,
    extraMetadata: dict[str, str | int | bool] | None = None,
) -> RunnableConfig:
    """Build the ``config`` for LangChain ``ainvoke`` calls.

    Carries ``run_name`` + ``tags`` + ``metadata`` always (cheap,
    serializable); ``callbacks`` only when tracing is configured.
    Never raises.
    """
    try:
        tags: list[str] = [*ctx.tags(), lane]
        metadata: dict[str, str | int | bool] = dict(ctx.metadata())
        if extraMetadata:
            metadata.update(extraMetadata)
        config: RunnableConfig = {
            "run_name": runName,
            "tags": tags,
            "metadata": metadata,
        }
        callbacks: list[BaseCallbackHandler] = createTraceCallbacks()
        if callbacks:
            config["callbacks"] = callbacks
        return config
    except Exception:
        return {"run_name": runName}


@contextmanager
def propagateReviewAttrs(
    *, ctx: ReviewTraceCtx, traceName: str | None = None
) -> Iterator[None]:
    """Set user/session attributes on nested observations.

    Wraps the Langfuse ``propagate_attributes`` context manager. All
    ``@observe`` spans and ``CallbackHandler`` generations created
    inside inherit ``user_id`` / ``session_id`` / ``tags`` /
    ``metadata``. No-op when tracing is disabled. Never raises on
    setup; body exceptions propagate unchanged.
    """
    if not settings.langfuse_configured:
        yield
        return
    try:
        from langfuse import propagate_attributes

        with propagate_attributes(
            user_id=ctx.userId,
            session_id=ctx.sessionId,
            tags=ctx.tags(),
            metadata=ctx.metadata(),
            version=settings.app_version,
            environment=settings.app_env,
            trace_name=traceName,
        ):
            yield
    except Exception:
        yield


def flushTraces() -> None:
    """Flush buffered Langfuse observations. Best-effort; never raises."""
    if not settings.langfuse_configured:
        return
    try:
        from langfuse import get_client

        get_client().flush()
    except Exception:
        return


__all__ = [
    "buildAgentConfig",
    "createTraceCallbacks",
    "flushTraces",
    "isTracingConfigured",
    "propagateReviewAttrs",
    "traceSessionId",
]
