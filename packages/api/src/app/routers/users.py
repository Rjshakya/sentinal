"""Users routes: surface the caller's indexed repos from the ``repos`` table.

Returns the rows that have already been created via the indexing flow,
filtered by the authenticated user from the session cookie.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlmodel import desc, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.db import get_session
from app.models.repo import Repo

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
