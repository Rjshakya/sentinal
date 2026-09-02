"""OpenLLMetry telemetry: SDK initialisation + FastAPI instrumentation.

This module is the single observability entry point for Sentinel. It
wires OpenTelemetry — `traceloop-sdk` (OpenLLMetry) for traces and
the OTel SDK log pipeline for logs — so every signal exports through
the same OTLP endpoint and can be forwarded to any collector. Two
surfaces are exported:

- :func:`init_telemetry` — initialises traces **and** logs **at import
  time** (called from ``main.py``), gated on
  :attr:`app.core.config.Settings.telemetry_configured`. When no OTLP
  endpoint or API key is set the SDK is never touched, so an
  unconfigured process pays zero overhead and never auto-generates a
  Traceloop-cloud key.

- :func:`instrument_fastapi` — attaches the official
  ``opentelemetry-instrumentation-fastapi`` ASGI instrumentation to
  the FastAPI app. Traceloop's own instrument set covers LLM
  providers, vector DBs, and agent frameworks only — there is no
  FastAPI instrumentor in the SDK, so the contrib package (already a
  dependency) is wired here and exports through the same OTLP
  pipeline the SDK set up.

How the pieces fit together:

- **Traces.** Every LLM call the review agents make (both lanes +
  both extractor steps) goes through LangChain chat models built by
  :func:`app.services.llm.service.createLLMModel`; the SDK's
  LangChain + provider instrumentations auto-capture those as
  ``gen_ai`` spans with model, token usage, and latency. No call-site
  changes were needed.
- **Logs.** A stdlib ``logging`` :class:`LoggingHandler` is attached
  to the root logger, so every ``log.info(...)`` / ``log.error(...)``
  call in the codebase becomes an OTel log record exported to
  ``<endpoint>/v1/logs`` alongside the traces. ``extra`` kwargs on a
  call (e.g. ``structured_data``) are surfaced as LogRecord
  attributes. The console handler configured by ``logging.basicConfig``
  stays in place, so logs still print locally.
- The webhook HTTP request itself gets a span from
  :func:`instrument_fastapi`. The durable review workflow runs
  fire-and-forget (``DBOS.start_workflow_async``), so the LLM spans
  root at the ``review`` workflow span created by the
  ``@traceloop.sdk.decorators.workflow(name="review")`` decorator on
  :func:`app.workflows.review.workflow.reviewWorkflow`, not under the
  HTTP span; :func:`Traceloop.set_association_properties` tags both
  sides with the same repo / pr / head / user keys as the join.
- Prompt / completion capture is controlled by the
  ``TRACELOOP_TRACE_CONTENT`` env var (the SDK 0.62 ``init`` has no
  ``trace_content`` parameter; every shipped instrumentation reads
  the env var instead), so :func:`init_telemetry` sets it from
  :attr:`Settings.telemetry_trace_content` before initialising.
- The SDK's own anonymous telemetry is disabled
  (``telemetry_enabled=False``).
"""

from __future__ import annotations

import logging
import os

from fastapi import FastAPI
from opentelemetry import _logs as otel_logs
from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk.resources import Resource
from traceloop.sdk import Traceloop

from app.core.config import settings

log = logging.getLogger(__name__)

APP_NAME = settings.app_name
"""The ``service.name`` resource attribute attached to every span/log."""

APP_ENV = settings.app_env
"""The ``env`` resource attribute attached to every span/log."""


def _log_endpoint() -> str:
    """Resolve the OTLP logs endpoint next to the trace endpoint.

    With ``TRACELOOP_BASE_URL`` set, logs export to
    ``<base_url>/v1/logs`` — the same collector the trace exporter
    targets. With only ``TRACELOOP_API_KEY`` set, logs export to
    Traceloop Cloud, mirroring traceloop's default base URL.
    """
    base_url = settings.telemetry_base_url.rstrip("/")
    return f"{base_url}/v1/logs"


def _init_log_export() -> None:
    """Route stdlib logging to OTLP via the OTel SDK log pipeline.

    Creates a :class:`LoggerProvider` with a batching OTLP/HTTP log
    exporter, registers it as the global provider, and attaches a
    :class:`LoggingHandler` to the root logger. Every stdlib
    ``log.info`` / ``log.error`` call in the codebase then becomes an
    OTel log record; ``extra`` kwargs on a call are carried over as
    LogRecord attributes (see the module docstring).
    """
    provider = LoggerProvider(
        resource=Resource.create({"service.name": APP_NAME, "env": APP_ENV})
    )
    provider.add_log_record_processor(
        BatchLogRecordProcessor(OTLPLogExporter(endpoint=_log_endpoint()))
    )
    otel_logs.set_logger_provider(provider)

    logging.getLogger().addHandler(
        LoggingHandler(level=logging.INFO, logger_provider=provider)
    )


def init_telemetry() -> None:
    """Initialise OpenTelemetry traces + logs when an endpoint or key is set.

    No-op (with a log line) when :attr:`Settings.telemetry_configured`
    is false — the SDK is never imported-into-action, so an
    unconfigured process incurs zero overhead.

    Called once at import time from ``main.py``. OpenTelemetry
    instrumentors patch already-imported modules, so running this
    after the routers have imported LangChain / provider packages is
    safe.
    """
    if not settings.telemetry_configured:
        log.info(
            "telemetry not configured (TRACELOOP_BASE_URL / TRACELOOP_API_KEY empty); "
            "skipping init"
        )
        return

    os.environ["TRACELOOP_TRACE_CONTENT"] = (
        "true" if settings.telemetry_trace_content else "false"
    )
    os.environ["TRACELOOP_TELEMETRY"] = "false"

    api_key: str | None = settings.telemetry_api_key or None
    axiom_dataset = settings.axiom_dataset

    if api_key and axiom_dataset:
        Traceloop.init(
            app_name=APP_NAME,
            api_endpoint=settings.telemetry_base_url,
            api_key=api_key,
            disable_batch=settings.telemetry_disable_batch,
            telemetry_enabled=False,
            resource_attributes={"env": APP_ENV},
            headers={
                "Authorization": f"Bearer {api_key}",
                "X-Axiom-Dataset": axiom_dataset,
            },
        )
    else:

        Traceloop.init(
            app_name=APP_NAME,
            api_endpoint=settings.telemetry_base_url,
            api_key=api_key,
            disable_batch=settings.telemetry_disable_batch,
            telemetry_enabled=False,
            resource_attributes={"env": APP_ENV},
        )

    _init_log_export()

    log.info(
        "telemetry initialised: base_url=%s logs_endpoint=%s env=%s trace_content=%s",
        settings.telemetry_base_url or "<traceloop-cloud-default>",
        _log_endpoint(),
        APP_ENV,
        settings.telemetry_trace_content,
    )


def instrument_fastapi(app: FastAPI) -> None:
    """Attach the OTLP ASGI instrumentation to ``app``.

    Called at the end of ``create_app()`` in ``main.py``, after the
    routers are registered. Skipped when telemetry is unconfigured or
    :attr:`Settings.telemetry_fastapi` is false. Every request then
    produces one HTTP span (route, method, status, latency) exported
    through the SDK's OTLP pipeline.
    """

    FastAPIInstrumentor().instrument_app(app)
    log.info("fastapi telemetry instrumentation attached")


__all__ = ["APP_NAME", "init_telemetry", "instrument_fastapi"]
