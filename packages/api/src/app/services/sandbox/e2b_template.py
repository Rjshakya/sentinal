"""E2B code-sandbox template builders.

Pre-baked E2B template used for agent sandboxes: the stock
``code-interpreter-v1`` image plus the ``sentinel-codegraph`` CLI the
review agents' ``search_codegraph`` tool shells out to. Rebuilt by CI
on every push that touches the template inputs (see
``.github/workflows/build-template.yml``); the review pipeline picks
it up via ``settings.e2b_template`` with no code change.
The single owner of the codegraph distribution pin is
:const:`CODEGRAPH_PCK_NAME` — the review step
(:mod:`app.workflows.review_v2.steps.codegraph_index`) imports it so
the baked image and the per-run install can never diverge.
"""

from __future__ import annotations

import logging
from typing import Any

from e2b import LogEntry, Template
from e2b.template.main import TemplateBuilder

from app.core.config import settings

log = logging.getLogger(__name__)

CODE_SANDBOX_TEMPLATE_NAME: str = "sentinel-sanbox"
CODE_SANDBOX_CPU: int = 2
CODE_SANDBOX_MEM_IN_MB: int = 1024 * 2

CODEGRAPH_PCK_NAME: str = "sentinel-codegraph==0.3.0"
"""Pinned codegraph distribution baked into the template (bump on release)."""


def base_e2b_template() -> TemplateBuilder:
    template: TemplateBuilder = (
        Template()
        .from_template("code-interpreter-v1")
        .run_cmd(f"pip install {CODEGRAPH_PCK_NAME}")
    )
    return template


def log_e2b_template_build(data: LogEntry) -> None:
    log.info(data.message)


def build_e2b_template():
    build_info = Template.build(
        base_e2b_template(),
        CODE_SANDBOX_TEMPLATE_NAME,
        cpu_count=CODE_SANDBOX_CPU,
        memory_mb=CODE_SANDBOX_MEM_IN_MB,
        api_key=settings.e2b_api_key,
        on_build_logs=log_e2b_template_build,
    )
    return build_info


__all__ = [
    "CODEGRAPH_PCK_NAME",
    "CODE_SANDBOX_CPU",
    "CODE_SANDBOX_MEM_IN_MB",
    "CODE_SANDBOX_TEMPLATE_NAME",
    "base_e2b_template",
    "build_e2b_template",
    "log_e2b_template_build",
]
