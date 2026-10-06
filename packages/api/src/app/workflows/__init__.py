"""Durable review pipelines, built on the service layer.

- ``triggers/`` — webhook-edge adapters: pure payload extraction plus
  one best-effort Lambda Invoke per delivery.
- ``durable/`` — the durable handlers (``opened_handler.py``,
  ``comment_handler.py``, ``repair_handler.py``), the shared
  ``pipeline.py`` / ``repair_pipeline.py`` agent phases, and flat
  ``steps/`` (one cohesive file per phase).
- ``review_v2/`` — the worker library consumed by ``durable/steps/``:
  sandbox/LLM/agent workers, input/result types, and the error
  hierarchy.
"""

from __future__ import annotations
