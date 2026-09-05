"""Typed errors for the sandbox service.

All errors are :class:`BaseModel` values **returned** (never raised)
by the sandbox service entry points; callers discriminate with
``isinstance``.
"""

from __future__ import annotations
from typing import Literal

from pydantic import BaseModel

from app.utils.branded import RepoId, UserId


class SandboxProviderError(BaseModel):
    """Provider-level failure (create / connect / kill).

    Returned by the provider classes (:mod:`app.services.sandbox.e2b`)
    as the error variant of their ``T | SandboxProviderError`` unions.
    """

    message: str
    userId: UserId | None = None
    repoId: RepoId | None = None
    id: str | None = None
    provider: Literal["e2b", "daytona"]

    def __str__(self) -> str:
        return self.message


__all__ = ["SandboxProviderError"]