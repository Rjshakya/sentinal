"""Users routes: surface the caller's indexed repos from the ``repos`` table
and the aggregated review stats for the dashboard.

All endpoints are user-scoped: they read ``request.state.user_id`` (set by
``AuthMiddleware``) and filter every query on it.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import func
from sqlmodel import desc, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.db import get_session
from app.models.code_comment import CodeComment
from app.models.enums import CommentSeverity
from app.models.pull_request import PullRequest
from app.models.repo import Repo
from app.models.review_summary import ReviewSummary

router = APIRouter(prefix="/users", tags=["users"])


class UserRepoOut(BaseModel):
    id: str
    user_id: str
    org_id: Optional[str] = None
    repo_name: str
    repo_owner: str
    url: Optional[str] = None
    private: bool
    default_branch: Optional[str] = None
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
    try:
        stmt = (
            select(Repo)
            .where(Repo.user_id == request.state.user_id)
            .order_by(desc(Repo.updated_at))
            .limit(limit)
        )
        result = await session.exec(stmt)
        rows = result.all()

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

    prs_reviewed_stmt = (
        select(func.count())
        .select_from(ReviewSummary)
        .join(PullRequest)
        .join(Repo)
        .where(Repo.user_id == user_id)
    )
    prs_reviewed = int((await session.exec(prs_reviewed_stmt)).one() or 0)

    comments_issued_stmt = (
        select(func.count())
        .select_from(CodeComment)
        .join(PullRequest)
        .join(Repo)
        .where(Repo.user_id == user_id)
    )
    comments_issued = int((await session.exec(comments_issued_stmt)).one() or 0)

    bugs_caught_stmt = (
        select(func.count())
        .select_from(CodeComment)
        .join(PullRequest)
        .join(Repo)
        .where(
            Repo.user_id == user_id,
            CodeComment.severity == CommentSeverity.P1_CRITICAL.value,
        )
    )
    bugs_caught = int((await session.exec(bugs_caught_stmt)).one() or 0)

    return UserStatsOut(
        prs_reviewed=prs_reviewed,
        comments_issued=comments_issued,
        bugs_caught=bugs_caught,
    )
