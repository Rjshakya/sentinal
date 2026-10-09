"""Observability service: flow-ctx assembly + backend-delegating scopes.

Public surface:

- :func:`createTraceCtx` / :func:`continueTraceCtx` — assemble or
  rebuild the serializable :class:`TraceCtx` (pure data — the join
  keys of one full flow; crosses durable boundaries).
- :func:`createObsCtx` — bind the live :class:`ObsBackend` to a flow
  ctx at the edge (never crosses a durable boundary).
- :func:`openScope` / :func:`closeScope` / :func:`eventInScope` /
  :func:`withScope` — generic span lifecycle over the injected
  backend.
- :func:`emitEvent` — one structured log row.
- :func:`countMetric` / :func:`observeLatency` — counter /
  histogram points.
- :func:`closeStepScope` / :func:`closeLlmScope` /
  :func:`closeGithubScope` / :func:`closeSandboxScope` /
  :func:`closeDbScope` — typed closers translating outcome values
  into consistent span status + attributes.

Naming convention: this package intentionally uses **camelCase**
identifiers — the same convention as :mod:`app.services.llm`,
:mod:`app.services.sandbox`, and :mod:`app.services.github`.
"""

from app.services.observability.errors import (
    ObsConfigError,
    ObsEmitError,
    ObsValidationError,
)
from app.services.observability.service import (
    closeDbScope,
    closeGithubScope,
    closeLlmScope,
    closeSandboxScope,
    closeScope,
    closeStepScope,
    continueTraceCtx,
    countMetric,
    createObsCtx,
    createTraceCtx,
    emitEvent,
    eventInScope,
    observeLatency,
    openScope,
    traceAttrs,
    withScope,
    withTraceAttrs,
)
from app.services.observability.otel_backend import (
    NoopObsBackend,
    OtelObsBackend,
    createOtelBackend,
)
from app.services.observability.types import (
    CommitId,
    DbOutcome,
    DeliveryId,
    EventName,
    ExecutionName,
    GithubOutcome,
    LlmOutcome,
    LlmPhase,
    LogLevel,
    MetricAttrs,
    MetricName,
    ObsBackend,
    ObsCtx,
    PRNumber,
    RepoId,
    ReviewRowId,
    SandboxOutcome,
    SpanAttrs,
    SpanHandle,
    SpanKind,
    SpanScope,
    SpanStatus,
    StepOutcome,
    StepStatus,
    TraceCtx,
    TraceId,
    TriggerKind,
    UserId,
)

__all__ = [
    "CommitId",
    "DbOutcome",
    "DeliveryId",
    "EventName",
    "ExecutionName",
    "GithubOutcome",
    "LlmOutcome",
    "LlmPhase",
    "LogLevel",
    "MetricAttrs",
    "MetricName",
    "NoopObsBackend",
    "ObsBackend",
    "ObsConfigError",
    "ObsCtx",
    "ObsEmitError",
    "ObsValidationError",
    "OtelObsBackend",
    "PRNumber",
    "RepoId",
    "ReviewRowId",
    "SandboxOutcome",
    "SpanAttrs",
    "SpanHandle",
    "SpanKind",
    "SpanScope",
    "SpanStatus",
    "StepOutcome",
    "StepStatus",
    "TraceCtx",
    "TraceId",
    "TriggerKind",
    "UserId",
    "closeDbScope",
    "closeGithubScope",
    "closeLlmScope",
    "closeSandboxScope",
    "closeScope",
    "closeStepScope",
    "continueTraceCtx",
    "countMetric",
    "createObsCtx",
    "createOtelBackend",
    "createTraceCtx",
    "emitEvent",
    "eventInScope",
    "observeLatency",
    "openScope",
    "traceAttrs",
    "withScope",
    "withTraceAttrs",
]
