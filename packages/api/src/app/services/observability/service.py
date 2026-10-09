"""Observability service: flow-ctx assembly + backend-delegating scopes.

Entry points:

- :func:`createTraceCtx` — mint the serializable flow ctx at webhook
  ingress (pure constructor).
- :func:`continueTraceCtx` — rebuild the flow ctx from a durable
  payload (validates; error is a value).
- :func:`createObsCtx` — bind the live backend to a flow ctx at the
  edge (pure constructor; the result never crosses a durable
  boundary).
- :func:`traceAttrs` / :func:`withTraceAttrs` — the canonical join-key
  attribute maps (``sentinel.*``).
- :func:`openScope` / :func:`closeScope` / :func:`eventInScope` /
  :func:`withScope` — generic span lifecycle over the injected
  backend.
- :func:`emitEvent` — one structured log (+ optional event name).
- :func:`countMetric` / :func:`observeLatency` — counter / histogram
  points over the injected backend.
- :func:`closeStepScope` / :func:`closeLlmScope` /
  :func:`closeGithubScope` / :func:`closeSandboxScope` /
  :func:`closeDbScope` — typed closers translating outcome values
  into consistent span status + attributes.

Error contract: **no function in this module raises, except**
:func:`withScope`, which re-raises the *caller's* exception after
recording an ``error`` close (it never raises its own errors).
Expected failures are returned values (``TraceCtx |
ObsValidationError``, ``None | ObsEmitError``); callers discriminate
with ``isinstance``.

Vendor neutrality: this module never imports an OTel SDK. All I/O
goes through the injected
:class:`app.services.observability.types.ObsBackend` subclass; tests
inject a fake, production injects OTel later.

Naming convention: this package intentionally uses **camelCase**
identifiers — the same convention as :mod:`app.services.llm`,
:mod:`app.services.sandbox`, and :mod:`app.services.github`.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from pydantic import ValidationError

from app.services.observability.errors import ObsEmitError, ObsValidationError
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
    TraceCtx,
    TraceId,
    TriggerKind,
    UserId,
)


def createTraceCtx(
    *,
    traceId: TraceId,
    delivery: DeliveryId,
    executionName: ExecutionName,
    trigger: TriggerKind,
    userId: UserId | None = None,
    repoId: RepoId | None = None,
    prNumber: PRNumber | None = None,
    headSha: CommitId | None = None,
    baseSha: CommitId | None = None,
    diffBaseSha: CommitId | None = None,
    reviewId: ReviewRowId | None = None,
) -> TraceCtx | ObsValidationError:
    """Mint the serializable flow ctx at webhook ingress.

    Pure constructor — no I/O. Returns ``ObsValidationError`` (never
    raises) when any field fails validation (e.g. an empty id).
    """
    try:
        return TraceCtx(
            traceId=traceId,
            delivery=delivery,
            executionName=executionName,
            trigger=trigger,
            userId=userId,
            repoId=repoId,
            prNumber=prNumber,
            headSha=headSha,
            baseSha=baseSha,
            diffBaseSha=diffBaseSha,
            reviewId=reviewId,
        )
    except ValidationError as exc:
        return ObsValidationError(
            message=f"invalid trace ctx: {exc.title}",
            issues=[str(issue) for issue in exc.errors()],
        )


def continueTraceCtx(raw: dict[str, object]) -> TraceCtx | ObsValidationError:
    """Rebuild the flow ctx from a durable payload.

    Validates the raw mapping against :class:`TraceCtx`; returns
    ``ObsValidationError`` (never raises) on any mismatch. The caller
    (durable handler entry) maps the error to its skip/fail result.
    """
    try:
        return TraceCtx.model_validate(raw)
    except ValidationError as exc:
        return ObsValidationError(
            message=f"invalid trace ctx: {exc.title}",
            issues=[str(issue) for issue in exc.errors()],
        )


def createObsCtx(trace: TraceCtx, backend: ObsBackend) -> ObsCtx:
    """Bind the live backend to a flow ctx at the edge.

    Pure constructor — no I/O. The result holds a live handle and
    must never cross a durable boundary; rebuild it per process.
    """
    return ObsCtx(trace=trace, backend=backend)


def traceAttrs(trace: TraceCtx) -> SpanAttrs:
    """Return the canonical join-key attribute map for a flow.

    Every span and log carries these keys so ``traceId`` alone
    returns the full flow in any backend. Metric label sets must
    *not* use these (see ``MetricAttrs`` cardinality rule).
    """
    attrs: SpanAttrs = {
        "sentinel.trace_id": str(trace.traceId),
        "sentinel.delivery": str(trace.delivery),
        "sentinel.execution_name": str(trace.executionName),
        "sentinel.trigger": str(trace.trigger),
    }
    if trace.prNumber is not None:
        attrs["sentinel.pr_number"] = int(trace.prNumber)
    if trace.headSha is not None:
        attrs["sentinel.head_sha"] = str(trace.headSha)
    if trace.reviewId is not None:
        attrs["sentinel.review_id"] = str(trace.reviewId)
    return attrs


def withTraceAttrs(trace: TraceCtx, extra: SpanAttrs | None = None) -> SpanAttrs:
    """Merge the join keys with one operation's extra attributes.

    Pure — no I/O. ``extra`` wins on key conflicts.
    """
    merged: SpanAttrs = traceAttrs(trace)
    if extra:
        merged.update(extra)
    return merged


def openScope(
    obs: ObsCtx,
    *,
    name: str,
    kind: SpanKind = "internal",
    attrs: SpanAttrs | None = None,
) -> SpanScope:
    """Open a span over the injected backend and return its scope.

    The backend never raises by contract, so this never raises. The
    caller closes the scope via :func:`closeScope` (or the
    ``with``-style :func:`withScope`).
    """
    handle: SpanHandle = obs.backend.openSpan(
        obs.trace, name, kind, attrs if attrs is not None else {}
    )
    return SpanScope(obs=obs, handle=handle, name=name, kind=kind)


def closeScope(
    scope: SpanScope,
    status: SpanStatus,
    attrs: SpanAttrs | None = None,
) -> None | ObsEmitError:
    """Close a scope with a status. Returns backend failures as values."""
    return scope.obs.backend.closeSpan(scope.handle, status, attrs)


def eventInScope(
    scope: SpanScope,
    event: str,
    attrs: SpanAttrs | None = None,
) -> None | ObsEmitError:
    """Record one timestamped event inside an open scope."""
    return scope.obs.backend.addSpanEvent(scope.handle, event, attrs)


@contextmanager
def withScope(
    obs: ObsCtx,
    *,
    name: str,
    kind: SpanKind = "internal",
    attrs: SpanAttrs | None = None,
) -> Iterator[SpanScope]:
    """Open a scope for a ``with`` block; close ``ok`` (clean exit).

    On a caller exception the scope closes ``error`` (carrying
    ``error.type`` / ``error.message``) and the exception propagates
    unchanged — the only ``raise`` in this module, and it is always
    the caller's own exception, never a new one.
    """
    scope: SpanScope = openScope(obs, name=name, kind=kind, attrs=attrs)
    try:
        yield scope
    except Exception as exc:
        closeScope(
            scope,
            "error",
            {
                "error.type": type(exc).__name__,
                "error.message": str(exc),
            },
        )
        raise
    else:
        closeScope(scope, "ok", None)


def emitEvent(
    obs: ObsCtx,
    *,
    event: EventName,
    level: LogLevel,
    message: str,
    attrs: SpanAttrs | None = None,
) -> None | ObsEmitError:
    """Write one structured log row (optionally named by ``event``)."""
    return obs.backend.emitLog(obs.trace, level, message, event, attrs)


def countMetric(
    obs: ObsCtx,
    *,
    metric: MetricName,
    value: int | float = 1,
    attrs: MetricAttrs | None = None,
) -> None | ObsEmitError:
    """Add a counter point. Returns backend failures as values."""
    return obs.backend.addCount(obs.trace, metric, value, attrs)


def observeLatency(
    obs: ObsCtx,
    *,
    metric: MetricName,
    seconds: int | float,
    attrs: MetricAttrs | None = None,
) -> None | ObsEmitError:
    """Record a duration point on a histogram. Unit is seconds."""
    return obs.backend.addHistogram(obs.trace, metric, seconds, attrs)


def closeStepScope(
    scope: SpanScope, outcome: StepOutcome
) -> None | ObsEmitError:
    """Close a durable-step scope with consistent status + attributes.

    ``succeeded`` / ``degraded`` close ``ok`` (degraded keeps a
    ``step.status="degraded"`` marker); ``failed`` closes ``error``.
    """
    if outcome.status == "failed":
        status: SpanStatus = "error"
    else:
        status = "ok"
    endAttrs: SpanAttrs = {"step.status": outcome.status}
    endAttrs["step.retryable"] = bool(outcome.retryable)
    if outcome.message is not None:
        endAttrs["step.message"] = outcome.message
    if outcome.attempt is not None:
        endAttrs["step.attempt"] = int(outcome.attempt)
    return closeScope(scope, status, endAttrs)


def closeLlmScope(
    scope: SpanScope,
    outcome: LlmOutcome,
    *,
    phase: LlmPhase,
    model: str,
) -> None | ObsEmitError:
    """Close an LLM-call scope with token + phase attributes."""
    endAttrs: SpanAttrs = {"llm.phase": phase, "llm.model": model}
    if outcome.inputTokens is not None:
        endAttrs["llm.input_tokens"] = int(outcome.inputTokens)
    if outcome.outputTokens is not None:
        endAttrs["llm.output_tokens"] = int(outcome.outputTokens)
    if outcome.cachedTokens is not None:
        endAttrs["llm.cached_tokens"] = int(outcome.cachedTokens)
    if outcome.message is not None:
        endAttrs["llm.message"] = outcome.message
    return closeScope(scope, outcome.status, endAttrs)


def closeGithubScope(
    scope: SpanScope,
    outcome: GithubOutcome,
    *,
    operation: str,
) -> None | ObsEmitError:
    """Close a GitHub-API scope with status-code attributes."""
    endAttrs: SpanAttrs = {"github.operation": operation}
    endAttrs["github.retryable"] = bool(outcome.retryable)
    if outcome.statusCode is not None:
        endAttrs["github.status_code"] = int(outcome.statusCode)
    if outcome.message is not None:
        endAttrs["github.message"] = outcome.message
    return closeScope(scope, outcome.status, endAttrs)


def closeSandboxScope(
    scope: SpanScope,
    outcome: SandboxOutcome,
    *,
    operation: str,
    providerId: str,
) -> None | ObsEmitError:
    """Close a sandbox-operation scope with exit-code attributes."""
    endAttrs: SpanAttrs = {
        "sandbox.operation": operation,
        "sandbox.provider": providerId,
    }
    if outcome.exitCode is not None:
        endAttrs["sandbox.exit_code"] = int(outcome.exitCode)
    if outcome.message is not None:
        endAttrs["sandbox.message"] = outcome.message
    return closeScope(scope, outcome.status, endAttrs)


def closeDbScope(
    scope: SpanScope,
    outcome: DbOutcome,
    *,
    table: str,
    operation: str,
) -> None | ObsEmitError:
    """Close a database-transaction scope with table attributes."""
    endAttrs: SpanAttrs = {"db.table": table, "db.operation": operation}
    if outcome.message is not None:
        endAttrs["db.message"] = outcome.message
    return closeScope(scope, outcome.status, endAttrs)


__all__ = [
    "closeDbScope",
    "closeGithubScope",
    "closeLlmScope",
    "closeSandboxScope",
    "closeScope",
    "closeStepScope",
    "continueTraceCtx",
    "countMetric",
    "createObsCtx",
    "createTraceCtx",
    "emitEvent",
    "eventInScope",
    "observeLatency",
    "openScope",
    "traceAttrs",
    "withScope",
    "withTraceAttrs",
]
