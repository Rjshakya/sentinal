"""Observability service: tiny functional facade over OTel.

The implementation lives in :mod:`app.core.telemetry` (the single
telemetry owner). This package only re-exports the six readable entry
points so service code imports from one stable place:

- :func:`init_telemetry` — start traces, metrics, logs.
- :func:`get_logger` — trace-correlated stdlib logger.
- :func:`with_span` — decorator adding one span to a function.
- :func:`start_span` — one span around a ``with`` block.
- :func:`count` / :func:`record` — counter / histogram points.

Naming convention: this package intentionally uses **snake_case**
identifiers — plain verbs matching the stdlib (``get_logger``,
``with_span``), unlike the camelCase service packages.
"""

from app.core.telemetry import (
    aforce_flush_telemetry,
    count,
    current_trace_id,
    extract_trace_context,
    force_flush_telemetry,
    get_logger,
    get_tracer,
    init_telemetry,
    inject_trace_context,
    is_telemetry_enabled,
    record,
    start_span,
    with_span,
)

trace_span = with_span
"""Backward-compatible alias for :func:`with_span`."""

__all__ = [
    "aforce_flush_telemetry",
    "count",
    "current_trace_id",
    "extract_trace_context",
    "force_flush_telemetry",
    "get_logger",
    "get_tracer",
    "init_telemetry",
    "inject_trace_context",
    "is_telemetry_enabled",
    "record",
    "start_span",
    "trace_span",
    "with_span",
]
