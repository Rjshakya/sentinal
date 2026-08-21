"""Step: resolve the local :class:`Repo` id for a trigger.

Two layers in this module, following the Functional Core / Imperative
Shell split:

- :func:`_load_repo_id` — the **pure** helper. Takes a session
  factory and a GitHub-side ``github_repo_id``, returns the local
  :class:`Repo.id` string or ``None``. No DBOS.
- :func:`resolve_repo_id_step` — the **DBOS-wrapped** step. Opens
  its own session and runs the same lookup. Returned id is the
  string-form UUID that DBOS uses as part of the inner
  ``review_workflow`` workflow id.
"""

from __future__ import annotations

import logging

from dbos import DBOS
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.db import async_session_maker
from app.models.repo import Repo

log = logging.getLogger(__name__)


async def _load_repo_id(
    session: AsyncSession,
    gh_repo_id: int,
) -> str | None:
    """Fetch the local :class:`Repo` id by GitHub-side ``github_repo_id``."""
    stmt = select(Repo.id).where(Repo.github_repo_id == gh_repo_id)
    result = await session.exec(stmt)
    repo_id = result.first()
    if repo_id is None:
        return None
    return str(repo_id)


@DBOS.step()
async def resolve_repo_id_step(gh_repo_id: int) -> str | None:
    """Durable DBOS step: load the local :class:`Repo.id` string.

    Returns ``None`` when no row matches; the workflow converts that
    to a ``skip_reason="repo_not_indexed"`` :class:`TriggerRunResult`.
    The returned id is the local UUID-string the inner
    ``review_workflow`` uses for its workflow id and for sandbox
    scoping.
    """
    async with async_session_maker() as session:
        repo_id = await _load_repo_id(session, gh_repo_id)

    if repo_id is None:
        log.info(
            "pr_issue_comment.resolve_repo_id_step: repo not indexed: "
            "gh_repo_id=%s",
            gh_repo_id,
        )
    return repo_id


__all__ = ["resolve_repo_id_step"]
