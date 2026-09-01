"""Step: resolve the per-user LLM context for a trigger.

Two layers in this module, following the Functional Core / Imperative
Shell split:

- :func:`_resolve_llm_ctx` — the **pure** helper. Calls
  :func:`app.services.llm.createUserLLMContext` and falls back to
  :func:`app.services.llm.createDefaultLLMContext` on
  :class:`app.services.llm.LLMContextError`. No DBOS.
- :func:`resolve_llm_config_step` — the **DBOS-wrapped** step.
  Returns the resolved :class:`app.services.llm.LLMCtx`.
"""

from __future__ import annotations

import logging

from dbos import DBOS

from app.core.db import async_session_maker
from app.services.llm import (
    LLMContextError,
    LLMCtx,
    createDefaultLLMContext,
    createUserLLMContext,
)
from app.utils.branded import UserId

log = logging.getLogger(__name__)


async def _resolve_llm_ctx(user_id: str) -> LLMCtx:
    """Return the :class:`LLMCtx` for the review workflow.

    Resolution order:

    1. The user's stored row in ``llm_configs`` (set via
       ``POST /api/llm_config``).
    2. The global settings-driven default
       (:func:`app.services.llm.createDefaultLLMContext`).
    """
    async with async_session_maker() as session:
        result = await createUserLLMContext(session, UserId(user_id))
    if isinstance(result, LLMContextError):
        log.info(
            "pr_issue_comment.resolve_llm_config_step: no user llm config, "
            "falling back to settings: user_id=%s",
            user_id,
        )
        return createDefaultLLMContext()
    return result


@DBOS.step()
async def resolve_llm_config_step(user_id: str) -> LLMCtx:
    """Durable DBOS step: load the per-user :class:`LLMCtx`.

    Returns the user's stored config when one exists, otherwise
    falls back to the env-driven default. The review workflow's
    gate (``settings.llm_configured``) is checked in the trigger
    workflow before this step is called.
    """
    return await _resolve_llm_ctx(user_id)


__all__ = ["resolve_llm_config_step"]