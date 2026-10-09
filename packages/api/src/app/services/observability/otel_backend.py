"""OTel + no-op backends for the observability service.

Production code injects :class:`OtelObsBackend` at the edge via
:func:`createOtelBackend`; tests and telemetry-disabled runs use
:class:`NoopObsBackend`. Both honour the ``ObsBackend`` never-raises
contract: export failures become :class:`ObsEmitError` values.
"""

from __future__ import annotations

import logging
import threading
import uuid
from typing import Any

from app.services.observability.errors import ObsEmitError
from app.services.observability.types import (
    LogLevel,
    MetricAttrs,
    MetricName,
    ObsBackend,
    SpanAttrs,
    SpanHandle,
    SpanKind,
    SpanStatus,
    TraceCtx,
)

log = logging.getLogger(__name__)


class NoopObsBackend(ObsBackend):
    """Discard everything. Used when telemetry is disabled or in tests."""

    def openSpan(
        self,
        trace: TraceCtx,
        name: str,
        kind: SpanKind,
        attrs: SpanAttrs,
    ) -> SpanHandle:
        _ = (trace, name, kind, attrs)
        return SpanHandle(f"noop-{uuid.uuid4().hex[:12]}")

    def closeSpan(
        self,
        handle: SpanHandle,
        status: SpanStatus,
        attrs: SpanAttrs | None = None,
    ) -> None | ObsEmitError:
        _ = (handle, status, attrs)
        return None

    def addSpanEvent(
        self,
        handle: SpanHandle,
        event: str,
        attrs: SpanAttrs | None = None,
    ) -> None | ObsEmitError:
        _ = (handle, event, attrs)
        return None

    def emitLog(
        self,
        trace: TraceCtx,
        level: LogLevel,
        message: str,
        event: str | None = None,
        attrs: SpanAttrs | None = None,
    ) -> None | ObsEmitError:
        _ = (trace, level, message, event, attrs)
        return None

    def addCount(
        self,
        trace: TraceCtx,
        metric: MetricName,
        value: int | float,
        attrs: MetricAttrs | None = None,
    ) -> None | ObsEmitError:
        _ = (trace, metric, value, attrs)
        return None

    def addHistogram(
        self,
        trace: TraceCtx,
        metric: MetricName,
        value: int | float,
        attrs: MetricAttrs | None = None,
    ) -> None | ObsEmitError:
        _ = (trace, metric, value, attrs)
        return None


_OTEL_KIND_MAP: dict[str, Any] = {}


def _otel_kind(kind: SpanKind) -> Any:
    try:
        from opentelemetry.trace import SpanKind as OTELKind

        return {
            "internal": OTELKind.INTERNAL,
            "server": OTELKind.SERVER,
            "client": OTELKind.CLIENT,
            "producer": OTELKind.PRODUCER,
            "consumer": OTELKind.CONSUMER,
        }[kind]
    except Exception:
        return None


def _status_for(status: SpanStatus) -> Any:
    try:
        from opentelemetry.trace import Status, StatusCode

        return Status(StatusCode.OK if status == "ok" else StatusCode.ERROR)
    except Exception:
        return None


class OtelObsBackend(ObsBackend):
    """OTel-backed spans/logs/metrics over the global SDK providers.

    Handle model: :meth:`openSpan` starts a real OTel span and stores
    ``(span, token)`` under a uuid handle; :meth:`closeSpan` ends it.
    Parenting follows the ambient OTel context at ``openSpan`` time, so
    nesting works when callers open scopes inside one process.
    """

    def __init__(self, *, tracer_name: str = "sentinel") -> None:
        self._tracer_name = tracer_name
        self._lock = threading.Lock()
        self._spans: dict[str, tuple[Any, Any]] = {}
        self._counters: dict[str, Any] = {}
        self._histograms: dict[str, Any] = {}

    def _tracer(self) -> Any:
        try:
            from app.core.telemetry import get_tracer

            return get_tracer(self._tracer_name)
        except Exception:
            return None

    def openSpan(
        self,
        trace: TraceCtx,
        name: str,
        kind: SpanKind,
        attrs: SpanAttrs,
    ) -> SpanHandle:
        try:
            from opentelemetry import trace as otel_trace

            tracer = self._tracer()
            merged: dict[str, Any] = {
                "sentinel.trace_id": str(trace.traceId),
                "sentinel.delivery": str(trace.delivery),
                "sentinel.execution_name": str(trace.executionName),
                "sentinel.trigger": str(trace.trigger),
            }
            for key, value in (attrs or {}).items():
                merged[str(key)] = value
            otel_kind = _otel_kind(kind)
            span = tracer.start_span(name, attributes=merged, kind=otel_kind)
            try:
                ctx = otel_trace.set_span_in_context(span)
                from opentelemetry import context as otel_context

                token = otel_context.attach(ctx)
            except Exception:
                token = None
            handle = SpanHandle(f"otel-{uuid.uuid4().hex}")
            with self._lock:
                self._spans[handle] = (span, token)
            return handle
        except Exception as exc:
            log.debug("otel backend openSpan failed: %s", exc)
            return SpanHandle(f"otel-degraded-{uuid.uuid4().hex[:12]}")

    def _take(self, handle: SpanHandle) -> tuple[Any, Any] | None:
        with self._lock:
            return self._spans.pop(str(handle), None)

    def _peek(self, handle: SpanHandle) -> tuple[Any, Any] | None:
        with self._lock:
            return self._spans.get(str(handle))

    def closeSpan(
        self,
        handle: SpanHandle,
        status: SpanStatus,
        attrs: SpanAttrs | None = None,
    ) -> None | ObsEmitError:
        entry = self._take(handle)
        if entry is None:
            return None
        span, token = entry
        try:
            if span is not None:
                if attrs:
                    for key, value in attrs.items():
                        try:
                            span.set_attribute(str(key), value)
                        except Exception:
                            continue
                otel_status = _status_for(status)
                if otel_status is not None:
                    try:
                        span.set_status(otel_status)
                    except Exception:
                        pass
                try:
                    span.end()
                except Exception:
                    pass
            if token is not None:
                try:
                    from opentelemetry import context as otel_context

                    otel_context.detach(token)
                except Exception:
                    pass
            return None
        except Exception as exc:
            return ObsEmitError(message=f"closeSpan failed: {exc}")

    def addSpanEvent(
        self,
        handle: SpanHandle,
        event: str,
        attrs: SpanAttrs | None = None,
    ) -> None | ObsEmitError:
        entry = self._peek(handle)
        if entry is None or entry[0] is None:
            return None
        try:
            entry[0].add_event(str(event), attributes=dict(attrs or {}))
            return None
        except Exception as exc:
            return ObsEmitError(message=f"addSpanEvent failed: {exc}")

    def emitLog(
        self,
        trace: TraceCtx,
        level: LogLevel,
        message: str,
        event: str | None = None,
        attrs: SpanAttrs | None = None,
    ) -> None | ObsEmitError:
        try:
            logger = logging.getLogger("sentinel.flow")
            extra_attrs = {
                "sentinel.trace_id": str(trace.traceId),
                "sentinel.delivery": str(trace.delivery),
                "sentinel.execution_name": str(trace.executionName),
            }
            if event:
                extra_attrs["sentinel.event"] = str(event)
            for key, value in (attrs or {}).items():
                extra_attrs[f"sentinel.{key}"] = value  # type: ignore[assignment]
            if level == "warn":
                logger.warning("%s", message, extra={"otel_attrs": extra_attrs})
            elif level == "error":
                logger.error("%s", message, extra={"otel_attrs": extra_attrs})
            else:
                logger.info("%s", message, extra={"otel_attrs": extra_attrs})
            return None
        except Exception as exc:
            return ObsEmitError(message=f"emitLog failed: {exc}", event=event)

    def _counter(self, metric: MetricName) -> Any:
        with threading.Lock():
            pass
        if metric in self._counters:
            return self._counters[metric]
        try:
            from app.core.telemetry import get_counter

            inst = get_counter(f"sentinel.{metric}", description=str(metric))
        except Exception:
            inst = None
        self._counters[metric] = inst
        return inst

    def _histogram(self, metric: MetricName) -> Any:
        if metric in self._histograms:
            return self._histograms[metric]
        try:
            from app.core.telemetry import get_histogram

            inst = get_histogram(f"sentinel.{metric}", description=str(metric))
        except Exception:
            inst = None
        self._histograms[metric] = inst
        return inst

    def addCount(
        self,
        trace: TraceCtx,
        metric: MetricName,
        value: int | float,
        attrs: MetricAttrs | None = None,
    ) -> None | ObsEmitError:
        _ = trace
        try:
            inst = self._counter(metric)
            if inst is None:
                return None
            inst.add(value, attributes=dict(attrs or {}))
            return None
        except Exception as exc:
            return ObsEmitError(message=f"addCount failed: {exc}", metric=str(metric))

    def addHistogram(
        self,
        trace: TraceCtx,
        metric: MetricName,
        value: int | float,
        attrs: MetricAttrs | None = None,
    ) -> None | ObsEmitError:
        _ = trace
        try:
            inst = self._histogram(metric)
            if inst is None:
                return None
            inst.record(value, attributes=dict(attrs or {}))
            return None
        except Exception as exc:
            return ObsEmitError(
                message=f"addHistogram failed: {exc}", metric=str(metric)
            )


def createOtelBackend() -> ObsBackend:
    """Return the OTel backend when enabled, else the no-op backend."""
    try:
        from app.core.telemetry import is_telemetry_enabled

        if is_telemetry_enabled():
            return OtelObsBackend()
    except Exception:
        pass
    return NoopObsBackend()


__all__ = ["NoopObsBackend", "OtelObsBackend", "createOtelBackend"]
