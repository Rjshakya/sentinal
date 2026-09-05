"""Reviews routes: surface the caller's review runs from the ``review``
table, joined with the repo / PR context and the token usage row.

All endpoints are user-scoped: they read ``request.state.user_id`` (set by
``AuthMiddleware``) and filter every query on it.
"""

from __future__ import annotations

from datetime import datetime
from typing import cast

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy.sql.elements import ColumnElement
from sqlmodel import desc, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.db import get_session
from app.models.enums import ReviewRunStatus
from app.models.pull_request import PullRequest
from app.models.repo import Repo
from app.models.review import Review, ReviewState
from app.models.review_usage import ReviewUsage

router = APIRouter(prefix="/review", tags=["review"])


class ReviewUsageOut(BaseModel):
    """Token usage for a single review run (one row per run)."""

    input_tokens: int
    output_tokens: int
    total_tokens: int
    review_status: ReviewRunStatus


class ReviewOut(BaseModel):
    """One review run with repo / PR context and its usage row.

    The usage join is a left join: runs without a persisted usage row
    (e.g. an early lifecycle failure) surface ``usage=None``.
    """

    id: str
    repo_name: str | None = None
    repo_owner: str | None = None
    pr_number: int
    pr_title: str | None = None
    commit_id: str
    trigger: str | None = None
    state: ReviewState
    comment_count: int | None = None
    llm_client: str | None = None
    llm_model: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    created_at: datetime
    usage: ReviewUsageOut | None = None


@router.get("", response_model=list[ReviewOut])
async def list_reviews(
    request: Request,
    session: AsyncSession = Depends(get_session),
    limit: int = Query(50, ge=1, le=100),
) -> list[ReviewOut]:
    """List the caller's review runs, newest first.

    One query left-joins the ``review`` row with its repo, PR, and usage
    rows. The onclause casts mirror the ``repositories/base.py`` pattern
    to keep pyright happy with SQLModel instrumented-attribute equality.
    """
    try:
        stmt = (
            select(Review, Repo, PullRequest, ReviewUsage)
            .outerjoin(Repo, cast(ColumnElement[bool], Review.repo_id == Repo.id))
            .outerjoin(
                PullRequest,
                cast(ColumnElement[bool], Review.pr_id == PullRequest.id),
            )
            .outerjoin(
                ReviewUsage,
                cast(ColumnElement[bool], ReviewUsage.review_id == Review.id),
            )
            .where(Review.user_id == request.state.user_id)
            .order_by(desc(Review.created_at))
            .limit(limit)
        )
        result = await session.exec(stmt)
        rows = result.all()
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to list reviews")

    return [
        ReviewOut(
            id=review.id,
            repo_name=repo.repo_name if repo is not None else None,
            repo_owner=repo.repo_owner if repo is not None else None,
            pr_number=review.pr_number,
            pr_title=pr.title if pr is not None else None,
            commit_id=review.commit_id,
            trigger=review.trigger,
            state=review.state,
            comment_count=review.comment_count,
            llm_client=review.llm_client,
            llm_model=review.llm_model,
            started_at=review.started_at,
            completed_at=review.completed_at,
            created_at=review.created_at,
            usage=(
                ReviewUsageOut(
                    input_tokens=usage.input_tokens,
                    output_tokens=usage.output_tokens,
                    total_tokens=usage.total_tokens,
                    review_status=usage.review_status,
                )
                if usage is not None
                else None
            ),
        )
        for review, repo, pr, usage in rows
    ]
