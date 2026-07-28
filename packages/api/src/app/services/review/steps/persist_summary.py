"""Persist the review summary row."""

from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import ReviewVerdict
from app.models.review_summary import ReviewSummary
from app.services.agent.models import ReviewResult

log = logging.getLogger(__name__)


async def persist_review_summary(
    session: AsyncSession,
    *,
    pr_id: str,
    commit_id: str,
    result: ReviewResult,
) -> ReviewSummary:
    """Insert a single :class:`ReviewSummary` row."""
    summary = ReviewSummary(
        pr_id=pr_id,
        commit_id=commit_id,
        summary=result.summary,
        verdict=ReviewVerdict(result.verdict),
    )
    session.add(summary)
    await session.flush()
    await session.refresh(summary)
    log.info(
        "persisted review summary: summary_id=%s pr_id=%s verdict=%s",
        summary.id,
        pr_id,
        summary.verdict,
    )
    return summary


__all__: list[str] = ["persist_review_summary"]
