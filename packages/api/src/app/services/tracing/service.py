"""Tracing service: Langfuse handler factory + flush.

Entry points (camelCase, matching the package convention):

- :func:`isTracingConfigured` — True when Langfuse keys are set.
- :func:`createTraceCallbacks` — one Langfuse ``CallbackHandler`` for an
  agent ``ainvoke`` call, or ``[]`` when tracing is disabled.
- :func:`flushTraces` — best-effort flush for short-lived processes
  (scripts, Lambda handlers). Never raises.

Error contract: **no function in this module raises.** Langfuse client
construction and flush are best-effort; a missing/invalid config simply
yields no callbacks. Services keep their error-as-value contract —
tracing never changes a return value.

Credentials: the Langfuse keys live in settings (process env /
Secrets Manager) and are read by the Langfuse client itself. They are
never carried on spans and never enter span metadata.

Trace attributes (user/session/tags/metadata) are set once by the
durable parent (``runAgentPhase`` / ``runRepairPhase``) with raw
``propagate_attributes``. Agent steps only pass ``config={"callbacks":
[...] }`` — no per-step trace ctx.

Naming convention: this package intentionally uses **camelCase**
identifiers — the same convention as :mod:`app.services.github`,
:mod:`app.services.llm`, and :mod:`app.services.sandbox`.
"""

from __future__ import annotations

from langchain_core.callbacks import BaseCallbackHandler

from app.core.config import settings


def isTracingConfigured() -> bool:
    """True when Langfuse keys are set (traces actually export)."""
    return settings.langfuse_configured


def createTraceCallbacks() -> list[BaseCallbackHandler]:
    """Create the Langfuse handler for one agent call.

    Returns ``[]`` when tracing is disabled or the handler fails to
    build, so callers can always pass the result into ``config``
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
    "createTraceCallbacks",
    "flushTraces",
    "isTracingConfigured",
]
