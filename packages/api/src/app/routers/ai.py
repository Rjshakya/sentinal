"""AI routes: the repository configure endpoint.

``POST /ai/repo/setup`` is synchronous — it bulk-inserts one ``Repo``
row per requested GitHub repo and returns the per-repo outcome
immediately (``200 OK``). No checks, no sandbox, no DBOS workflow, no
polling. The dashboard only ever sends repos with
``is_configured=False``.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Request, status

from app.core.db import async_session_maker
from app.models.repo import Repo
from app.routers.schemas.ai import (
    ConfiguredRepo,
    ConfigureResponse,
    SetupRequest,
)
from app.utils.util import uuidToStr

log = logging.getLogger(__name__)

router = APIRouter(prefix="/ai", tags=["ai"])


@router.post(
    "/repo/setup",
    status_code=status.HTTP_200_OK,
    response_model=ConfigureResponse,
)
async def configure_repos(
    payload: SetupRequest,
    request: Request,
) -> ConfigureResponse:
    """Bulk-insert one ``Repo`` row per requested repo."""
    user_id: str = request.state.user_id

    rows: list[Repo] = [
        Repo(
            id=uuidToStr(),
            user_id=user_id,
            github_repo_id=r.id,
            repo_name=r.name,
            repo_owner=r.owner,
            clone_url=f"https://github.com/{r.owner}/{r.name}.git",
            url=f"https://github.com/{r.owner}/{r.name}",
            private=False,
            default_branch=r.default_branch,
        )
        for r in payload.repos
    ]

    async with async_session_maker() as session:
        session.add_all(rows)
        await session.commit()

    log.info(
        "ai.configure: ok user_id=%s count=%d",
        user_id,
        len(rows),
    )

    return ConfigureResponse(
        repos=[
            ConfiguredRepo(
                github_repo_id=row.github_repo_id,
                repo_id=row.id,
            )
            for row in rows
        ]
    )


__all__ = ["configure_repos", "router"]
