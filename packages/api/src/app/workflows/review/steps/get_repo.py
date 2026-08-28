"""Get the local repo record for a review.

Two layers, following the new service conventions:

- :func:`getRepo` — the **pure** helper. Takes the caller's
  :class:`AsyncSession` and the GitHub repo id, returns a
  :class:`RepoSnapshot` or a :class:`RepoGetError` value. No DBOS, no
  raising.
- :func:`getRepoTx` — the **DBOS-wrapped** transaction edge. Acquires
  the DBOS datasource session, calls the pure helper, and raises a
  :class:`ReviewStepFailure` when the repo is unknown (a business
  outcome the workflow lets propagate).
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.core.db import dbos_datasource
from app.models.repo import Repo as RepoModel
from app.utils.branded import RepoId, RepoName, RepoOwner
from app.workflows.review.errors import RepoGetError, ReviewStepFailure
from app.workflows.review.types import RepoSnapshot


async def getRepo(
    session: AsyncSession,
    *,
    ghRepoId: int,
) -> RepoSnapshot | RepoGetError:
    """Fetch the local :class:`Repo` row by its GitHub-side id."""
    repo = (
        (await session.execute(select(RepoModel).where(RepoModel.github_repo_id == ghRepoId)))
        .scalars()
        .first()
    )
    if repo is None:
        return RepoGetError(message=f"repo {ghRepoId!r} not found")
    return RepoSnapshot(
        id=RepoId(repo.id),
        repoOwner=RepoOwner(repo.repo_owner),
        repoName=RepoName(repo.repo_name),
        defaultBranch=repo.default_branch,
    )


@dbos_datasource.transaction()
async def getRepoTx(*, ghRepoId: int) -> RepoSnapshot:
    """Durable DBOS transaction: find the local repo row by GitHub repo id.

    Raises:
        ReviewStepFailure: no row matches ``ghRepoId`` (wrapping a
            :class:`RepoGetError`). Business outcome — not retried.
    """
    session = dbos_datasource.sql_session()
    result = await getRepo(session, ghRepoId=ghRepoId)
    if isinstance(result, RepoGetError):
        raise ReviewStepFailure(result)
    return result


__all__ = ["getRepo", "getRepoTx"]