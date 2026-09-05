"""Typed errors for the LLM service.

- :class:`LLMConfigError` — a malformed ``"provider:model"`` string (or a
  provider-construction failure). Returned (never raised) by
  :func:`app.services.llm.service.createLLMModel` as the error variant of
  its ``BaseChatModel | LLMConfigError`` union. The class itself subclasses
  :class:`ValueError` so callers can still ``raise`` it if they ever need
  to escalate a returned error into an exception.

Expected failure modes of the per-user context creator (no stored row,
DB read failure) are also **values**: it returns
:class:`app.services.llm.types.LLMContextError` as the error variant of
its ``LLMCtx | LLMContextError`` union.
"""

from __future__ import annotations

from pydantic import BaseModel

from app.utils.branded import UserId


class LLMConfigError(ValueError):
    """Malformed ``"provider:model"`` string or provider-construction failure.

    Returned by :func:`app.services.llm.service.createLLMModel` when
    ``ctx.model`` lacks the ``":"`` separator or the resolved provider
    rejects the configuration.
    """


class LLMContextError(BaseModel):
    """Error variant of the ``LLMCtx | LLMContextError`` creator union.

    Returned (never raised) by
    :func:`app.services.llm.service.createUserLLMContext` for every
    expected failure: no stored row for the user, or a DB read failure.
    ``userId`` is populated by the creator so callers can correlate
    without re-reading it.
    """

    message: str
    userId: UserId | None = None

    def __str__(self) -> str:
        return self.message


__all__ = ["LLMConfigError", "LLMContextError"]
