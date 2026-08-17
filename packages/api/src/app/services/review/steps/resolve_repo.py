"""Resolve the local repo record for a review.

Two layers in this module, following the Functional Core / Imperative
Shell split:

- :func:`resolve_repo` — the **pure** helper. Takes a
  :class:`app.repositories.Repository` and returns the :class:`Repo`
  row. No DBOS, no sessions, no I/O outside the repository call.
  Useful for tests and for any future caller that already has a
  repository.
- :func:`resolve_repo_tx` — the **DBOS-wrapped** transaction. Acquires
  the DBOS datasource session, runs the same lookup, and returns a
  :data:`app.services.review.workflow_types.RepoSnapshot` (the
  serialisable subset that can cross a workflow boundary). This is
  what :func:`app.services.review.workflow.review_workflow` calls.
"""

from __future__ import annotations

from sqlmodel import select

from app.core.db import dbos_datasource
from app.models.repo import Repo as RepoModel
from app.repositories import Repository
from app.services.review.errors import RepoNotFoundError
from app.services.review.workflow_types import RepoSnapshot


async def resolve_repo(
    *,
    gh_repo_id: int,
    repository: Repository[RepoModel],
) -> RepoModel:
    """Fetch the local :class:`Repo` row by its GitHub-side id.

    Pure helper. Raises:
        RepoNotFoundError: when no row matches ``gh_repo_id``.
    """
    record = await repository.find_by_field(RepoModel.github_repo_id, gh_repo_id)
    if record is None:
        raise RepoNotFoundError(repo_id=str(gh_repo_id))
    return record


@dbos_datasource.transaction()
async def resolve_repo_tx(gh_repo_id: int) -> RepoSnapshot:
    """Durable DBOS transaction: find the local repo row by GitHub repo id.

    The transaction is DBOS-managed so it retries transient DB failures
    automatically. Returns a :class:`RepoSnapshot` (the serialisable
    subset) because DBOS cannot persist a SQLModel ORM object across
    the workflow boundary.

    Raises:
        RepoNotFoundError: no row matches ``gh_repo_id``. This is a
            business outcome and is not retried.
    """
    session = dbos_datasource.sql_session()
    result = await session.execute(
        select(RepoModel).where(RepoModel.github_repo_id == gh_repo_id)
    )
    repo = result.scalar_one_or_none()
    if repo is None:
        raise RepoNotFoundError(repo_id=str(gh_repo_id))
    return RepoSnapshot(
        id=repo.id,
        repo_name=repo.repo_name,
        repo_owner=repo.repo_owner,
        default_branch=repo.default_branch,
    )


__all__ = ["resolve_repo", "resolve_repo_tx"]
