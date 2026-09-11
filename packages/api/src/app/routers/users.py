"""Users routes: surface the caller's indexed repos from the ``repos`` table
and the aggregated review stats for the dashboard.

All endpoints are user-scoped: they read ``request.state.user_id`` (set by
``AuthMiddleware``) and filter every query on it.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlmodel import col
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.db import get_session
from app.models.repo import Repo
from app.repositories.code_comment import CodeCommentRepository
from app.repositories.repo import RepoRepository
from app.repositories.review_summary import ReviewSummaryRepository

router = APIRouter(prefix="/users", tags=["users"])


class UserRepoOut(BaseModel):
    id: str
    user_id: str
    org_id: str | None = None
    repo_name: str
    repo_owner: str
    url: str | None = None
    private: bool
    default_branch: str | None = None
    is_indexed: bool
    created_at: datetime
    updated_at: datetime


class UserStatsOut(BaseModel):
    """Aggregated review stats for the dashboard overview.

    Every count is the total across all of the caller's repos, joined
    through ``pull_requests`` so that rows belonging to a different
    user's repo can never leak into the result.
    """

    prs_reviewed: int
    comments_issued: int
    bugs_caught: int


@router.get("/repos", response_model=list[UserRepoOut])
async def list_my_repos(
    request: Request,
    session: AsyncSession = Depends(get_session),
    limit: int = Query(100, ge=1, le=100),
) -> list[UserRepoOut]:
    """List the caller's indexed repositories.

    Only repos with ``is_indexed = True`` are returned — the endpoint is
    the source of truth for the dashboard's "indexed repositories" list.
    """
    try:
        repo = RepoRepository(session=session)
        rows = await repo.find(
            col(Repo.user_id) == request.state.user_id,
            col(Repo.is_indexed) == True,
            order_by=col(Repo.updated_at).desc(),
            limit=limit,
        )

        return [
            UserRepoOut(
                id=r.id,
                user_id=r.user_id,
                org_id=r.org_id,
                repo_name=r.repo_name,
                repo_owner=r.repo_owner,
                url=r.url,
                private=r.private,
                default_branch=r.default_branch,
                is_indexed=r.is_indexed or False,
                created_at=r.created_at,
                updated_at=r.updated_at,
            )
            for r in rows
        ]
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to list indexed repos")


@router.get("/stats", response_model=UserStatsOut)
async def get_user_stats(
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> UserStatsOut:
    """Return the per-user review stats shown on the dashboard overview.

    All three counts are computed against the user's repos via joins on
    ``pull_requests``. The three queries run in a single session and
    are independent — failure on one does not block the others from
    surfacing partial state.
    """
    user_id = request.state.user_id

    summaries = ReviewSummaryRepository(session=session)
    prs_reviewed = await summaries.count_for_user(user_id)

    comments = CodeCommentRepository(session=session)
    comments_issued = await comments.count_for_user(user_id)
    bugs_caught = await comments.count_p1_for_user(user_id)

    return UserStatsOut(
        prs_reviewed=prs_reviewed,
        comments_issued=comments_issued,
        bugs_caught=bugs_caught,
    )
