"""Typed errors for the observability service.

All errors are :class:`BaseModel` values **returned** (never raised)
by the observability service entry points; callers discriminate with
``isinstance``.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class ObsValidationError(BaseModel):
    """Malformed flow identity (bad ``TraceCtx`` input).

    Returned (never raised) by
    :func:`app.services.observability.service.createTraceCtx` and
    :func:`app.services.observability.service.continueTraceCtx` when
    the input fails validation. ``issues`` carries one entry per
    rejected field.
    """

    message: str
    issues: list[str] = Field(default_factory=list)

    def __str__(self) -> str:
        return self.message


class ObsEmitError(BaseModel):
    """Backend export failure (span close / log / metric).

    Returned (never raised) by the backend-delegating entry points in
    :mod:`app.services.observability.service` when the injected
    :class:`app.services.observability.types.ObsBackend` reports a
    failure. Callers treat it as best-effort telemetry loss: the flow
    itself never fails because observability failed.
    """

    message: str
    metric: str | None = None
    event: str | None = None

    def __str__(self) -> str:
        return self.message


class ObsConfigError(BaseModel):
    """Invalid observability configuration (bad endpoint or headers).

    Reserved for the future backend factory (the OTel client builder).
    This package never reads settings today; the error type exists so
    the factory's ``T | ObsConfigError`` union is stable from day one.
    """

    message: str

    def __str__(self) -> str:
        return self.message


__all__ = ["ObsConfigError", "ObsEmitError", "ObsValidationError"]
