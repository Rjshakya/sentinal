"""Observability service types.

This module owns the *contract* of the observability service: the
serializable :class:`TraceCtx` (pure data — everything needed to join
one full flow), the live :class:`ObsCtx` (identity + injected
backend), the :class:`ObsBackend` vendor interface, span scopes, and
the outcome models the typed close helpers consume.

Naming convention: this package intentionally uses **camelCase**
identifiers — the same convention as :mod:`app.services.llm`,
:mod:`app.services.sandbox`, and :mod:`app.services.github`. Ids that
are also identifiers (id, ctx) keep their single-word lowercase form.

Design notes:

- :class:`TraceCtx` is a plain Pydantic model (durable-serializable)
  so it can cross workflow boundaries (it rides inside the durable
  event payloads and step inputs). It carries only join keys and
  domain identity — never diff text, prompts, or completions. Those
  stay on spans/logs as gated attributes, never in the ctx.
- Ids are **branded types** (``NewType`` over ``str``): they erase to
  ``str`` at runtime (Pydantic validation and durable serialization
  are unaffected) but pyright enforces the branding statically, so a
  bare ``str`` cannot accidentally flow into a ctx. Domain ids
  (``UserId``, ``RepoId``, ``PRNumber``, ``CommitId``,
  ``ReviewRowId``) are reused from :mod:`app.utils.branded`; the
  flow-owned ids live here.
- :class:`ObsCtx` carries the live backend. It is **not**
  serializable — the edge rebuilds it per process via
  :func:`app.services.observability.service.createObsCtx` and it
  never crosses a durable boundary (same rule as ``PRCtx``).
- :class:`ObsBackend` is an abstract base: the single vendor seam. The
  service functions consume it; tests inject a fake, production
  injects OTel later. The backend never raises — export failures are
  returned as :class:`ObsEmitError` values.
- Metric labels stay low-cardinality by contract: file paths, SHAs,
  delivery ids, and execution names go on spans/logs only, never on
  metric label sets (see ``MetricAttrs``).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Literal, NewType

from pydantic import BaseModel, ConfigDict, Field

from app.services.observability.errors import ObsEmitError
from app.utils.branded import CommitId, PRNumber, RepoId, ReviewRowId, UserId

TraceId = NewType("TraceId", str)
"""Branded flow id (hex uuid), minted once at webhook ingress."""

DeliveryId = NewType("DeliveryId", str)
"""Branded ``X-GitHub-Delivery`` value."""

ExecutionName = NewType("ExecutionName", str)
"""Branded durable execution name (== ``review.workflow_id``)."""

SpanHandle = NewType("SpanHandle", str)
"""Opaque span token minted by the backend; passed back on close/event."""

TriggerKind = Literal["opened", "comment", "repair"]
"""Which edge started the flow."""

SpanKind = Literal["internal", "server", "client", "producer", "consumer"]
"""OTel span kinds."""

LogLevel = Literal["info", "warn", "error"]
"""Structured-log levels."""

SpanStatus = Literal["ok", "error"]
"""Closed-span status."""

StepStatus = Literal["succeeded", "failed", "degraded"]
"""Durable-step outcome (``retrying`` is a span *event*, not a close)."""

LlmPhase = Literal["planner", "file", "extract", "summary", "repair"]
"""Which agent lane produced the LLM call."""

EventName = Literal[
    "webhookReceived",
    "webhookRejected",
    "webhookDispatched",
    "triggerInvokeStarted",
    "triggerInvokeSucceeded",
    "triggerInvokeFailed",
    "handlerStarted",
    "handlerCtxResolved",
    "handlerSkipped",
    "handlerCompleted",
    "handlerFailed",
    "stepStarted",
    "stepSucceeded",
    "stepFailed",
    "stepRetrying",
    "stepDegraded",
    "dbTx",
    "githubApiCall",
    "sandboxOp",
    "llmCall",
    "reviewPersisted",
    "reviewPosted",
    "reviewBacklinked",
    "repairDispatched",
]
"""Closed vocabulary of flow events (span names + log events)."""

MetricName = Literal[
    "webhookDeliveries",
    "webhookRejected",
    "durableInvokes",
    "durableInvokeErrors",
    "handlerDuration",
    "stepDuration",
    "stepFailures",
    "stepDegraded",
    "llmCalls",
    "llmTokens",
    "llmDuration",
    "sandboxOpDuration",
    "sandboxErrors",
    "githubCalls",
    "githubDuration",
    "githubRateLimited",
    "dbTxDuration",
    "dbTxErrors",
    "reviewComments",
    "reviewVerdict",
    "reviewPosted",
    "repairDispatched",
    "sandboxKillFailures",
]
"""Closed vocabulary of counters and histograms."""

SpanAttrs = dict[str, str | int | float | bool]
"""Span/log attribute map. Full IDs live here."""

MetricAttrs = dict[str, str]
"""Metric label map. Low-cardinality string labels only."""


class TraceCtx(BaseModel):
    """Join keys + domain identity of one flow, as pure serializable data.

    Assembled by
    :func:`app.services.observability.service.createTraceCtx` at
    webhook ingress (or rebuilt from a durable payload via
    :func:`app.services.observability.service.continueTraceCtx`);
    consumed by
    :func:`app.services.observability.service.createObsCtx` at each
    edge to bind the live backend.
    """

    traceId: TraceId = Field(min_length=1)
    delivery: DeliveryId = Field(min_length=1)
    executionName: ExecutionName = Field(min_length=1)
    trigger: TriggerKind
    userId: UserId | None = None
    repoId: RepoId | None = None
    prNumber: PRNumber | None = None
    headSha: CommitId | None = None
    baseSha: CommitId | None = None
    diffBaseSha: CommitId | None = None
    reviewId: ReviewRowId | None = None


class ObsBackend(ABC):
    """Vendor seam: span / log / metric sinks. Never raises.

    Abstract base (mirrors ``BaseSandboxService``): the service
    functions consume it, tests subclass it with a fake, production
    subclasses it with OTel. A plain class keeps Pydantic's
    ``isinstance`` schema valid for the :class:`ObsCtx` field (a
    ``Protocol`` is not a valid ``isinstance`` target).
    """

    @abstractmethod
    def openSpan(
        self,
        trace: TraceCtx,
        name: str,
        kind: SpanKind,
        attrs: SpanAttrs,
    ) -> SpanHandle: ...

    @abstractmethod
    def closeSpan(
        self,
        handle: SpanHandle,
        status: SpanStatus,
        attrs: SpanAttrs | None = None,
    ) -> None | ObsEmitError: ...

    @abstractmethod
    def addSpanEvent(
        self,
        handle: SpanHandle,
        event: str,
        attrs: SpanAttrs | None = None,
    ) -> None | ObsEmitError: ...

    @abstractmethod
    def emitLog(
        self,
        trace: TraceCtx,
        level: LogLevel,
        message: str,
        event: str | None = None,
        attrs: SpanAttrs | None = None,
    ) -> None | ObsEmitError: ...

    @abstractmethod
    def addCount(
        self,
        trace: TraceCtx,
        metric: MetricName,
        value: int | float,
        attrs: MetricAttrs | None = None,
    ) -> None | ObsEmitError: ...

    @abstractmethod
    def addHistogram(
        self,
        trace: TraceCtx,
        metric: MetricName,
        value: int | float,
        attrs: MetricAttrs | None = None,
    ) -> None | ObsEmitError: ...


class ObsCtx(BaseModel):
    """Identity of one flow in this process + its injected backend."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    trace: TraceCtx
    backend: ObsBackend


class SpanScope(BaseModel):
    """One open span: the obs it belongs to plus the backend handle."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    obs: ObsCtx
    handle: SpanHandle
    name: str
    kind: SpanKind


class StepOutcome(BaseModel):
    """Value object describing how a durable step closed."""

    status: StepStatus
    retryable: bool = False
    message: str | None = None
    attempt: int | None = Field(default=None, ge=0)


class LlmOutcome(BaseModel):
    """Value object describing how one LLM call closed."""

    status: SpanStatus
    inputTokens: int | None = Field(default=None, ge=0)
    outputTokens: int | None = Field(default=None, ge=0)
    cachedTokens: int | None = Field(default=None, ge=0)
    message: str | None = None


class GithubOutcome(BaseModel):
    """Value object describing how one GitHub API call closed."""

    status: SpanStatus
    statusCode: int | None = None
    retryable: bool = False
    message: str | None = None


class SandboxOutcome(BaseModel):
    """Value object describing how one sandbox operation closed."""

    status: SpanStatus
    exitCode: int | None = None
    message: str | None = None


class DbOutcome(BaseModel):
    """Value object describing how one database transaction closed."""

    status: SpanStatus
    message: str | None = None


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
    "ObsBackend",
    "ObsCtx",
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
]
