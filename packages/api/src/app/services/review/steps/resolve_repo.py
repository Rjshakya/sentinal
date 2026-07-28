"""Resolve the local repo record for a review."""

from __future__ import annotations

from app.models.repo import Repo as RepoModel
from app.repositories import Repository
from app.services.review.errors import RepoNotFoundError


async def resolve_repo(
    *,
    gh_repo_id: int,
    repository: Repository[RepoModel],
) -> RepoModel:
    """Fetch the local :class:`Repo` row by its GitHub-side id.

    Raises:
        RepoNotFoundError: when no row matches ``gh_repo_id``.
    """
    record = await repository.find_by_field(RepoModel.github_repo_id, gh_repo_id)
    if record is None:
        raise RepoNotFoundError(repo_id=str(gh_repo_id))
    return record


__all__ = ["resolve_repo"]
