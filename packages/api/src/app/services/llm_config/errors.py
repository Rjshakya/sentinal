"""Typed errors for the per-user LLM config service.

Only one error is surfaced to the service layer:

- :class:`NoActiveLLMConfigError` — the user has no row in the
  ``llm_configs`` table. The webhook's ``resolve_llm_config``
  surfaces this so the workflow gets a clear failure mode for
  misconfigured users.

The test/probe path :func:`app.services.llm_config.test_user_llm_config`
**never raises**; it returns a structured
:class:`LLMTestResult` instead so the frontend can render the
outcome. Database write failures during upsert are caught inside
:func:`upsert_user_llm_config` and converted into a
``LLMTestResult`` with ``exception`` populated, so the upsert
endpoint always returns the same envelope shape regardless of
internal failure mode.
"""

from __future__ import annotations


class NoActiveLLMConfigError(Exception):
    """The user has no row in the ``llm_configs`` table.

    Raised by :func:`app.services.llm_config.resolve_active_llm_config`
    when the webhook is dispatching a review for a user who has
    not yet registered a custom LLM config (and the global
    ``settings.llm_config`` fallback is also unavailable).
    """

    def __init__(self, user_id: str) -> None:
        self.user_id = user_id
        super().__init__(f"no active LLM config for user {user_id!r}")


__all__ = ["NoActiveLLMConfigError"]
