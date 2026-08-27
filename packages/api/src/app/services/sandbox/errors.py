from __future__ import annotations
from typing import Literal

from pydantic import BaseModel

from app.utils.branded import RepoId, UserId


class SandboxServiceError(BaseModel):
    """Error variant of the ``LLMCtx | LLMContextError`` creator union.

    Returned (never raised) by
    :func:`app.services.llm.service.createDefaultLLMContext` and
    :func:`app.services.llm.service.createUserLLMContext` for every
    expected failure: LLM unset in settings, no stored row for the user,
    or a DB read failure. ``userId`` is populated by the per-user
    creator so callers can correlate without re-reading it.
    """

    message: str
    userId: UserId | None = None
    repoId: RepoId | None = None
    id: str | None = None

    def __str__(self) -> str:
        return self.message


class SandboxProviderError(BaseModel):
    """Error variant of the ``LLMCtx | LLMContextError`` creator union.

    Returned (never raised) by
    :func:`app.services.llm.service.createDefaultLLMContext` and
    :func:`app.services.llm.service.createUserLLMContext` for every
    expected failure: LLM unset in settings, no stored row for the user,
    or a DB read failure. ``userId`` is populated by the per-user
    creator so callers can correlate without re-reading it.
    """

    message: str
    userId: UserId | None = None
    repoId: RepoId | None = None
    id: str | None = None
    provider: Literal["e2b", "daytona"]

    def __str__(self) -> str:
        return self.message


__all__ = ["SandboxProviderError", "SandboxServiceError"]
