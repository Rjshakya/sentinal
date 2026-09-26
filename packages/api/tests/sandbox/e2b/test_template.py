"""Live tests for the pre-baked E2B sandbox template.

Unlike the rest of the suite these hit real E2B infrastructure: they
build the template and boot a sandbox from it, so they need
``E2B_API_KEY`` and take minutes. The verification sandbox is always
killed — a kill failure never masks the assertion.
"""

from __future__ import annotations

from e2b import AsyncSandbox
from e2b.sandbox.commands.command_handle import CommandExitException

import pytest

from app.core.config import settings
from app.services.sandbox.e2b_template import (
    CODE_SANDBOX_TEMPLATE_NAME,
    CODEGRAPH_PCK_NAME,
    build_e2b_template,
)

_CREATE_TIMEOUT_S: int = 20 * 60
"""Upper bound on booting the verification sandbox from the template."""

_COMMAND_TIMEOUT_S: int = 120
"""Upper bound on one in-sandbox verification command."""


def test_template_builds() -> None:
    build_info = build_e2b_template()
    assert build_info.template_id
    assert build_info.name == CODE_SANDBOX_TEMPLATE_NAME


async def test_sentinel_codegraph_exists() -> None:
    sandbox = await AsyncSandbox.create(
        template=CODE_SANDBOX_TEMPLATE_NAME,
        api_key=settings.e2b_api_key,
        timeout=_CREATE_TIMEOUT_S,
    )
    try:
        try:
            which = await sandbox.commands.run(
                "which codegraph", timeout=_COMMAND_TIMEOUT_S
            )
            assert "codegraph" in which.stdout

            help_out = await sandbox.commands.run(
                "codegraph --help", timeout=_COMMAND_TIMEOUT_S
            )
            assert "index" in help_out.stdout

            pinned_version: str = CODEGRAPH_PCK_NAME.split("==")[1]
            shown = await sandbox.commands.run(
                "pip show sentinel-codegraph", timeout=_COMMAND_TIMEOUT_S
            )
            assert pinned_version in shown.stdout
        except CommandExitException as exc:
            pytest.fail(
                "codegraph CLI broken: "
                f"exit={exc.exit_code} stderr={exc.stderr.strip()}"
            )
    finally:
        await sandbox.kill()
