"""Resolve the local repo record for a review."""

from __future__ import annotations

from app.core.result import Err, Ok, Result
from app.models.repo import Repo as RepoModel
from app.repositories import Repository
from app.services.review.errors import RepoNotFound


async def resolve_repo(
    *,
    gh_repo_id: int,
    repository: Repository[RepoModel],
) -> Result[RepoModel, RepoNotFound]:
    """Fetch the local :class:`Repo` row by its GitHub-side id.

    Returns ``Err(RepoNotFound)`` when no row matches.
    """
    record = await repository.find_by_field(RepoModel.github_repo_id, gh_repo_id)
    if record is None:
        return Err(RepoNotFound(repo_id=str(gh_repo_id)))
    return Ok(record)


__all__: list[str] = ["resolve_repo"]
