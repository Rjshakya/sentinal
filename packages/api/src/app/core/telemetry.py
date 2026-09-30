"""Observability seam: init + FastAPI instrumentation (strict types).

Kept as the single import point (``main.py`` calls both functions).
Bodies are dependency-free no-ops until the new instrument lands — no
``traceloop-sdk``, no OpenTelemetry imports. Logging stays plain stdlib
console via ``logging.basicConfig`` in ``main.py``.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI

log = logging.getLogger(__name__)


def init_telemetry() -> None:
    """No-op seam: new observability init lands here."""
    log.info("telemetry init: no-op seam (new instrument pending)")


def instrument_fastapi(app: FastAPI) -> None:
    """No-op seam: new FastAPI instrumentation lands here."""
    _ = app
    log.info("fastapi telemetry instrumentation: no-op seam")


__all__ = ["init_telemetry", "instrument_fastapi"]
