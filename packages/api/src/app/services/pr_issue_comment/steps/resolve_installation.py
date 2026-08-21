"""Step: resolve the local :class:`Installation` row for a trigger.

Two layers in this module, following the Functional Core / Imperative
Shell split:

- :func:`_load_installation` — the **pure** helper. Takes a session
  factory and an installation id, returns the row or ``None``. No
  DBOS, no workflow boundary.
- :func:`resolve_installation_step` — the **DBOS-wrapped** step.
  Opens its own session via :data:`app.core.db.async_session_maker`,
  runs the same lookup, and returns a
  :class:`app.services.pr_issue_comment.types.InstallationSnapshot`
  (the serialisable subset that can cross a workflow boundary).
"""

from __future__ import annotations

import logging

from dbos import DBOS
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.db import async_session_maker
from app.models.installation import Installation
from app.services.pr_issue_comment.types import InstallationSnapshot

log = logging.getLogger(__name__)


async def _load_installation(
    session: AsyncSession,
    github_installation_id: int,
) -> Installation | None:
    """Fetch the local :class:`Installation` row by GitHub-side id."""
    stmt = select(Installation).where(
        Installation.github_installation_id == github_installation_id,
    )
    return (await session.exec(stmt)).first()


@DBOS.step()
async def resolve_installation_step(
    github_installation_id: int,
) -> InstallationSnapshot | None:
    """Durable DBOS step: load the local :class:`Installation` row.

    Returns ``None`` when no row matches; the workflow converts that
    to a ``skip_reason="unowned_installation"`` :class:`TriggerRunResult`.
    Returns the typed :class:`InstallationSnapshot` (with the
    attached ``user_id``) so the workflow can dispatch the review
    under the owning user.
    """
    async with async_session_maker() as session:
        row = await _load_installation(session, github_installation_id)

    if row is None:
        log.info(
            "pr_issue_comment.resolve_installation_step: no installation: "
            "github_installation_id=%s",
            github_installation_id,
        )
        return None

    return InstallationSnapshot(
        id=row.id,
        account_login=row.account_login,
        user_id=row.user_id,
    )


__all__ = ["resolve_installation_step"]
