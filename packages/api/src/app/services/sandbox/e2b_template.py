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

from e2b import LogEntry, Template, default_build_logger
from e2b.template.main import TemplateBuilder

from app.core.config import settings

log = logging.getLogger(__name__)

CODE_SANDBOX_TEMPLATE_NAME: str = "sentinel-sanbox"
CODE_SANDBOX_CPU: int = 2
CODE_SANDBOX_MEM_IN_MB: int = 1024 * 4

CODEGRAPH_PCK_NAME: str = "sentinel-codegraph==0.3.0"
"""Pinned codegraph distribution baked into the template (bump on release)."""


def base_e2b_template() -> TemplateBuilder:
    template: TemplateBuilder = (
        Template()
        .from_python_image("3.13")
        .apt_install(["git", "curl", "grep", "ripgrep"])
        .run_cmd(
            [
                "curl -fsSL https://deb.nodesource.com/setup_lts.x -o nodesource_setup.sh",
                "sudo -E bash nodesource_setup.sh",
                "sudo apt install -y nodejs",
            ],
        )
        .run_cmd(
            [
                "node --version",
                "npm --version",
                "python --version",
                "pip --version",
            ]
        )
        .pip_install(f"{CODEGRAPH_PCK_NAME}")
        .npm_install("@earendil-works/pi-coding-agent@1.3.0", g=True)
        .run_cmd(["pi --version", "codegraph --help"])
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
        on_build_logs=default_build_logger(),
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
