"""Step: resolve the per-user LLM config for a trigger.

Two layers in this module, following the Functional Core / Imperative
Shell split:

- :func:`_resolve_llm` — the **pure** helper. Calls
  :func:`app.services.llm_config.resolve_active_llm_config` and
  falls back to :attr:`app.core.config.settings.llm_config` on
  :class:`app.services.llm_config.errors.NoActiveLLMConfigError`. No
  DBOS.
- :func:`resolve_llm_config_step` — the **DBOS-wrapped** step.
  Returns the resolved :class:`app.core.llm.LLMConfig`.
"""

from __future__ import annotations

import logging

from dbos import DBOS

from app.core.config import settings
from app.core.llm import LLMConfig
from app.services.llm_config import (
    NoActiveLLMConfigError,
    resolve_active_llm_config,
)

log = logging.getLogger(__name__)


async def _resolve_llm(user_id: str) -> LLMConfig:
    """Return the :class:`LLMConfig` for the review workflow.

    Resolution order:

    1. The user's stored row in ``llm_configs`` (set via
       ``POST /api/llm_configs``).
    2. The global :attr:`app.core.config.settings.llm_config` (admin
       escape hatch).
    """
    try:
        return await resolve_active_llm_config(user_id)
    except NoActiveLLMConfigError:
        log.info(
            "pr_issue_comment.resolve_llm_config_step: no user llm config, "
            "falling back to settings: user_id=%s",
            user_id,
        )
        return settings.llm_config


@DBOS.step()
async def resolve_llm_config_step(user_id: str) -> LLMConfig:
    """Durable DBOS step: load the per-user :class:`LLMConfig`.

    Returns the user's stored config when one exists, otherwise
    falls back to the env-driven default. The review_workflow's
    gate (``settings.llm_configured``) is checked in the trigger
    workflow before this step is called.
    """
    return await _resolve_llm(user_id)


__all__ = ["resolve_llm_config_step"]
