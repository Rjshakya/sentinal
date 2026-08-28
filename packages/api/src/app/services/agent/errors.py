"""Typed errors for the agent service.

All errors are :class:`BaseModel` values **returned** (never raised)
by :mod:`app.services.agent.service` entry points; callers
discriminate with ``isinstance``.

- :class:`AgentBuildError` — the error variant of every
  ``T | AgentBuildError`` union in the service (agent construction
  failures: ``create_deep_agent`` raising, middleware / backend
  construction failing).
"""

from __future__ import annotations

from pydantic import BaseModel

from app.utils.branded import CommitId, PRNumber, RepoId, UserId


class AgentBuildError(BaseModel):
    """Error variant of every ``T | AgentBuildError`` union in the
    agent service.

    Returned (never raised) by
    :func:`app.services.agent.service.createSummaryAgent` and
    :func:`app.services.agent.service.createCommentsAgent` when the
    deep-agent construction fails. The branded run identity is
    populated by the builder so callers can correlate without
    re-reading it.
    """

    message: str
    userId: UserId | None = None
    repoId: RepoId | None = None
    prNumber: PRNumber | None = None
    headSha: CommitId | None = None

    def __str__(self) -> str:
        return self.message


__all__ = ["AgentBuildError"]