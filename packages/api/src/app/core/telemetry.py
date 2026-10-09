"""Observability seam: OTel init + FastAPI instrumentation + span helpers.

Single import point (``main.py`` calls :func:`init_telemetry` then
:func:`instrument_fastapi`). When ``OTEL_EXPORTER_OTLP_ENDPOINT`` is empty
every helper is a no-op, so the same code runs locally and on Lambda.

Design notes (kept compatible with the service error-as-value pattern):

- :func:`init_telemetry` is idempotent and never raises.
- :func:`trace_span` never marks returned ``*Error`` values as span
  failures (type name ending in ``"Error"`` closes ``OK`` with an
  ``error.value`` marker); only a raised exception closes ``ERROR``.
- Trace propagation across the Lambda Invoke boundary is explicit:
  :func:`inject_trace_context` adds ``traceparent`` to the durable event
  payload, :func:`extract_trace_context` restores it in the handler.
"""

from __future__ import annotations

import functools
import inspect
import logging
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

from fastapi import FastAPI

log = logging.getLogger(__name__)

_initialized = False
_enabled = False
_init_lock = threading.Lock()
_tracer_provider: Any = None
_meter_provider: Any = None
_logger_provider: Any = None
_meter_cache_lock = threading.Lock()
_meter_instruments: dict[str, Any] = {}


def _join_endpoint(base: str, suffix: str) -> str:
    base = (base or "").strip().rstrip("/")
    if not base:
        return ""
    if base.endswith(suffix):
        return base
    return f"{base}{suffix}"


def is_telemetry_enabled() -> bool:
    """True when OTel exporters were initialised."""
    return _enabled


def init_telemetry() -> None:
    """Initialise OTel SDK providers once. Never raises."""
    global _initialized, _enabled
    global _tracer_provider, _meter_provider, _logger_provider
    with _init_lock:
        if _initialized:
            return
        _initialized = True
    try:
        from app.core.config import settings

        endpoint = (settings.otel_exporter_otlp_endpoint or "").strip()
        if not endpoint:
            log.info("telemetry init: disabled (no OTLP endpoint)")
            return

        from opentelemetry import metrics as otel_metrics
        from opentelemetry import trace as otel_trace
        from opentelemetry._logs import set_logger_provider as set_otel_logger_provider
        from opentelemetry.sdk._logs import LoggerProvider as SDKLoggerProvider
        from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
        from opentelemetry.sdk.metrics import MeterProvider as SDKMeterProvider
        from opentelemetry.sdk.metrics.export import (
            PeriodicExportingMetricReader,
        )
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider as SDKTracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.sdk.trace.sampling import (
            ParentBased,
            TraceIdRatioBased,
        )

        from opentelemetry.exporter.otlp.proto.http._log_exporter import (
            OTLPLogExporter,
        )
        from opentelemetry.exporter.otlp.proto.http.metric_exporter import (
            OTLPMetricExporter,
        )
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
            OTLPSpanExporter,
        )

        headers = settings.otlp_headers_dict
        resource = Resource.create(
            {
                "service.name": settings.otel_service_name or "sentinel-api",
                "service.version": "0.1.0",
                "deployment.environment": settings.app_env,
            }
        )
        ratio = max(0.0, min(1.0, float(settings.otel_sampler_arg)))
        sampler = ParentBased(root=TraceIdRatioBased(ratio))

        span_exporter = OTLPSpanExporter(
            endpoint=_join_endpoint(endpoint, "/v1/traces"),
            headers=headers,
            timeout=3,
        )
        _tracer_provider = SDKTracerProvider(
            resource=resource, sampler=sampler
        )
        _tracer_provider.add_span_processor(
            BatchSpanProcessor(
                span_exporter,
                schedule_delay_millis=2000,
                max_queue_size=512,
                max_export_batch_size=128,
                export_timeout_millis=3000,
            )
        )
        try:
            otel_trace.set_tracer_provider(_tracer_provider)
        except Exception:  # provider already set (tests / reload)
            pass

        metric_exporter = OTLPMetricExporter(
            endpoint=_join_endpoint(endpoint, "/v1/metrics"),
            headers=headers,
            timeout=3,
        )
        metric_reader = PeriodicExportingMetricReader(
            metric_exporter, export_interval_millis=60000, export_timeout_millis=3000
        )
        _meter_provider = SDKMeterProvider(
            resource=resource, metric_readers=[metric_reader]
        )
        try:
            otel_metrics.set_meter_provider(_meter_provider)
        except Exception:
            pass

        log_exporter = OTLPLogExporter(
            endpoint=_join_endpoint(endpoint, "/v1/logs"),
            headers=headers,
            timeout=3,
        )
        _logger_provider = SDKLoggerProvider(resource=resource)
        _logger_provider.add_log_record_processor(
            BatchLogRecordProcessor(log_exporter)
        )
        try:
            set_otel_logger_provider(_logger_provider)
        except Exception:
            pass

        _instrument_libraries()

        _enabled = True
        log.info(
            "telemetry init: enabled endpoint=%s service=%s sampler=%.3f",
            endpoint,
            settings.otel_service_name,
            ratio,
        )
    except Exception as exc:
        _enabled = False
        log.warning("telemetry init: failed (%s: %s)", type(exc).__name__, exc)


def _instrument_libraries() -> None:
    """Best-effort auto-instrumentation (never raises)."""
    try:
        from opentelemetry.instrumentation.logging import LoggingInstrumentor

        LoggingInstrumentor().instrument(set_logging_format=False)
    except Exception as exc:
        log.debug("telemetry: logging instrument skipped: %s", exc)
    try:
        from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor

        SQLAlchemyInstrumentor().instrument(enable_commenter=True)
    except Exception as exc:
        log.debug("telemetry: sqlalchemy instrument skipped: %s", exc)
    try:
        from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

        HTTPXClientInstrumentor().instrument()
    except Exception as exc:
        log.debug("telemetry: httpx instrument skipped: %s", exc)
    try:
        from opentelemetry.instrumentation.botocore import BotocoreInstrumentor

        BotocoreInstrumentor().instrument()
    except Exception as exc:
        log.debug("telemetry: botocore instrument skipped: %s", exc)


def _fastapi_request_hook(span: Any, scope: dict[str, Any]) -> None:
    """Attach GitHub delivery attributes to webhook server spans."""
    try:
        if span is None or not span.is_recording():
            return
        path = str(scope.get("path") or "")
        if "webhooks/github" not in path:
            return
        headers: dict[str, str] = {}
        raw = scope.get("headers") or []
        for key, value in raw:
            try:
                headers[bytes(key).decode("latin-1").lower()] = bytes(value).decode(
                    "latin-1"
                )
            except Exception:
                continue
        event = headers.get("x-github-event")
        delivery = headers.get("x-github-delivery")
        if event:
            span.set_attribute("github.event", event)
        if delivery:
            span.set_attribute("github.delivery", delivery)
    except Exception:
        pass


def instrument_fastapi(app: FastAPI) -> None:
    """Instrument one FastAPI app. Never raises; no-op when disabled."""
    try:
        if getattr(app, "_sentinel_otel_instrumented", False):
            return
        from app.core.config import settings

        if not _enabled or not settings.telemetry_fastapi:
            log.info("fastapi telemetry instrumentation: skipped (disabled)")
            return
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

        FastAPIInstrumentor().instrument_app(
            app,
            server_request_hook=_fastapi_request_hook,
            tracer_provider=_tracer_provider,
            meter_provider=_meter_provider,
            excluded_urls=settings.telemetry_excluded_urls,
            http_capture_headers_server_request=["X-GitHub-Event", "X-GitHub-Delivery"],
        )
        setattr(app, "_sentinel_otel_instrumented", True)
        log.info("fastapi telemetry instrumentation: enabled")
    except Exception as exc:
        log.warning("fastapi telemetry instrumentation: failed (%s)", exc)


def get_tracer(name: str = "sentinel") -> Any:
    """Return an OTel tracer (NoOp when telemetry is disabled)."""
    try:
        from opentelemetry import trace as otel_trace

        return otel_trace.get_tracer(name)
    except Exception:
        return _NoopTracer()


class _NoopSpan:
    def __enter__(self) -> _NoopSpan:
        return self

    def __exit__(self, *args: Any) -> bool:
        return False

    def set_attribute(self, *args: Any, **kwargs: Any) -> None:
        pass

    def add_event(self, *args: Any, **kwargs: Any) -> None:
        pass

    def set_status(self, *args: Any, **kwargs: Any) -> None:
        pass

    def record_exception(self, *args: Any, **kwargs: Any) -> None:
        pass

    def is_recording(self) -> bool:
        return False

    def get_span_context(self) -> Any:
        return None


class _NoopTracer:
    def start_as_current_span(self, *args: Any, **kwargs: Any) -> _NoopSpan:
        return _NoopSpan()


@contextmanager
def start_span(
    name: str,
    attributes: dict[str, Any] | None = None,
    kind: Any = None,
) -> Iterator[Any]:
    """Open a child span of the current context. Never raises."""
    try:
        from opentelemetry import trace as otel_trace

        kwargs: dict[str, Any] = {"attributes": dict(attributes or {})}
        if kind is not None:
            kwargs["kind"] = kind
        with otel_trace.get_tracer("sentinel").start_as_current_span(
            name, **kwargs
        ) as span:
            yield span
    except Exception:
        yield _NoopSpan()


def _is_error_value(result: Any) -> bool:
    """Detect service error-values (``*Error`` models) without importing them."""
    try:
        name = type(result).__name__
        if not name.endswith("Error"):
            return False
        # Pydantic error models carry a message; success payloads do not
        # share the naming convention, so the suffix check is sufficient.
        return hasattr(result, "message") or hasattr(result, "model_dump")
    except Exception:
        return False


def trace_span(
    name: str,
    *,
    attrs_from: Callable[..., dict[str, Any]] | None = None,
    kind: Any = None,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Decorate a service function with one OTel span.

    Compatible with the error-as-value contract: a returned ``*Error``
    model closes the span ``OK`` (with ``error.value=true``); only a
    raised exception closes ``ERROR`` and re-raises.
    """

    def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
        is_coro = inspect.iscoroutinefunction(fn)

        @functools.wraps(fn)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            if not _enabled:
                return await fn(*args, **kwargs)
            attrs: dict[str, Any] = {}
            if attrs_from is not None:
                try:
                    attrs = dict(attrs_from(*args, **kwargs) or {})
                except Exception:
                    attrs = {}
            try:
                with start_span(name, attributes=attrs, kind=kind) as span:
                    try:
                        result = await fn(*args, **kwargs)
                    except Exception as exc:
                        try:
                            span.record_exception(exc)
                            from opentelemetry.trace import Status, StatusCode

                            span.set_status(
                                Status(StatusCode.ERROR, str(exc)[:256])
                            )
                        except Exception:
                            pass
                        raise
                    try:
                        if _is_error_value(result):
                            span.set_attribute("error.value", True)
                        elif isinstance(attrs, dict) and attrs:
                            pass
                    except Exception:
                        pass
                    return result
            except Exception:
                # start_span itself is defensive; this path only runs when
                # the wrapped call raised (re-raised above) — keep it.
                raise

        @functools.wraps(fn)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            if not _enabled:
                return fn(*args, **kwargs)
            attrs: dict[str, Any] = {}
            if attrs_from is not None:
                try:
                    attrs = dict(attrs_from(*args, **kwargs) or {})
                except Exception:
                    attrs = {}
            with start_span(name, attributes=attrs, kind=kind) as span:
                try:
                    result = fn(*args, **kwargs)
                except Exception as exc:
                    try:
                        span.record_exception(exc)
                        from opentelemetry.trace import Status, StatusCode

                        span.set_status(Status(StatusCode.ERROR, str(exc)[:256]))
                    except Exception:
                        pass
                    raise
                try:
                    if _is_error_value(result):
                        span.set_attribute("error.value", True)
                except Exception:
                    pass
                return result

        return async_wrapper if is_coro else sync_wrapper

    return decorator


def inject_trace_context(payload: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of ``payload`` carrying the current traceparent."""
    try:
        from opentelemetry import propagate

        carrier: dict[str, str] = {}
        propagate.inject(carrier)
        if not carrier:
            return dict(payload)
        out = dict(payload)
        if carrier.get("traceparent"):
            out["traceparent"] = carrier["traceparent"]
        if carrier.get("tracestate"):
            out["tracestate"] = carrier["tracestate"]
        return out
    except Exception:
        return dict(payload)


def extract_trace_context(payload: dict[str, Any]) -> Any:
    """Restore the OTel context from a payload carrying ``traceparent``."""
    try:
        from opentelemetry import propagate

        carrier: dict[str, str] = {}
        tp = payload.get("traceparent") if isinstance(payload, dict) else None
        ts = payload.get("tracestate") if isinstance(payload, dict) else None
        if isinstance(tp, str) and tp:
            carrier["traceparent"] = tp
        if isinstance(ts, str) and ts:
            carrier["tracestate"] = ts
        if not carrier:
            return None
        return propagate.extract(carrier)
    except Exception:
        return None


def current_trace_id() -> str:
    """Return the current OTel trace id as 32-hex, else ``""``."""
    try:
        from opentelemetry import trace as otel_trace

        ctx = otel_trace.get_current_span().get_span_context()
        if ctx is None or not ctx.is_valid:
            return ""
        return format(ctx.trace_id, "032x")
    except Exception:
        return ""


def force_flush_telemetry(timeout_millis: int = 1000) -> bool:
    """Flush all providers. Best-effort; never raises."""
    if not _enabled:
        return True
    ok = True
    deadline = time.time() + max(timeout_millis, 1) / 1000.0
    try:
        if _tracer_provider is not None:
            remaining = max(1, int((deadline - time.time()) * 1000))
            ok = bool(_tracer_provider.force_flush(remaining)) and ok
    except Exception as exc:
        log.debug("telemetry flush traces failed: %s", exc)
        ok = False
    try:
        if _meter_provider is not None:
            remaining = max(1, int((deadline - time.time()) * 1000))
            ok = bool(_meter_provider.force_flush(remaining)) and ok
    except Exception as exc:
        log.debug("telemetry flush metrics failed: %s", exc)
        ok = False
    try:
        if _logger_provider is not None:
            remaining = max(1, int((deadline - time.time()) * 1000))
            ok = bool(_logger_provider.force_flush(remaining)) and ok
    except Exception as exc:
        log.debug("telemetry flush logs failed: %s", exc)
        ok = False
    return ok


async def aforce_flush_telemetry(timeout_millis: int = 1000) -> bool:
    """Async flush (runs the blocking flush in a worker thread)."""
    if not _enabled:
        return True
    import asyncio

    try:
        return await asyncio.to_thread(force_flush_telemetry, timeout_millis)
    except Exception:
        return False


def get_counter(name: str, description: str = "", unit: str = "1") -> Any:
    """Return (and cache) an OTel Counter. NoOp when disabled."""
    key = f"counter:{name}"
    with _meter_cache_lock:
        if key in _meter_instruments:
            return _meter_instruments[key]
    try:
        from opentelemetry import metrics as otel_metrics

        meter = otel_metrics.get_meter("sentinel")
        inst = meter.create_counter(name, description=description, unit=unit)
    except Exception:
        inst = _NoopInstrument()
    with _meter_cache_lock:
        _meter_instruments[key] = inst
    return inst


def get_histogram(name: str, description: str = "", unit: str = "s") -> Any:
    """Return (and cache) an OTel Histogram. NoOp when disabled."""
    key = f"histogram:{name}"
    with _meter_cache_lock:
        if key in _meter_instruments:
            return _meter_instruments[key]
    try:
        from opentelemetry import metrics as otel_metrics

        meter = otel_metrics.get_meter("sentinel")
        inst = meter.create_histogram(name, description=description, unit=unit)
    except Exception:
        inst = _NoopInstrument()
    with _meter_cache_lock:
        _meter_instruments[key] = inst
    return inst


class _NoopInstrument:
    def add(self, *args: Any, **kwargs: Any) -> None:
        pass

    def record(self, *args: Any, **kwargs: Any) -> None:
        pass


__all__ = [
    "aforce_flush_telemetry",
    "current_trace_id",
    "extract_trace_context",
    "force_flush_telemetry",
    "get_counter",
    "get_histogram",
    "get_tracer",
    "init_telemetry",
    "inject_trace_context",
    "instrument_fastapi",
    "is_telemetry_enabled",
    "start_span",
    "trace_span",
]
