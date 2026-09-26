"""E2B code-sandbox template builders.

Pre-baked E2B template used for agent sandboxes (e.g. the manual
:mod:`scripts.test_llm_provider` smoke test). The review pipeline
itself provisions sandboxes through :mod:`app.services.sandbox.e2b`
and does not depend on these builders.
"""

from __future__ import annotations

import logging
from typing import Any

from e2b import LogEntry, Template

from app.core.config import settings

log = logging.getLogger(__name__)

CODE_SANDBOX_TEMPLATE_NAME: str = "SENTINAL_CODE_SANDBOX_TEMP"
CODE_SANDBOX_CPU: int = 2
CODE_SANDBOX_MEM_IN_MB: int = 1024 * 2


def base_e2b_template() -> Any:
    template: Any = (
        Template()
        .from_python_image()
        .set_user("root")
        .run_cmd("mkdir -p /conversation_history")
    )
    return template


def log_e2b_template_build(data: LogEntry) -> None:
    log.info(data.message)


def build_e2b_template() -> Any:
    build_info: Any = Template.build(
        base_e2b_template(),
        CODE_SANDBOX_TEMPLATE_NAME,
        cpu_count=CODE_SANDBOX_CPU,
        memory_mb=CODE_SANDBOX_MEM_IN_MB,
        api_key=settings.e2b_api_key,
        on_build_logs=log_e2b_template_build,
    )
    return build_info


__all__ = [
    "CODE_SANDBOX_CPU",
    "CODE_SANDBOX_MEM_IN_MB",
    "CODE_SANDBOX_TEMPLATE_NAME",
    "base_e2b_template",
    "build_e2b_template",
    "log_e2b_template_build",
]
