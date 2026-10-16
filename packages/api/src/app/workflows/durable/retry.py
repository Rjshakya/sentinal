"""Retry policies for durable step calls.

``RETRY_3`` retries transient infra and persist failures (3 attempts in
total). ``RETRY_1`` runs a step once with no retry, for degrade steps and
steps whose failure the pipeline handles itself.
"""

from __future__ import annotations

from async_durable_execution import RetryStrategy

RETRY_3 = RetryStrategy(max_attempts=3)
RETRY_1 = RetryStrategy(max_attempts=1)

__all__ = ["RETRY_1", "RETRY_3"]
