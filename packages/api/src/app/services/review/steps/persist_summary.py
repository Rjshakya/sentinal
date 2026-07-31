"""Persist the review summary row.

Two layers, following the Functional Core / Imperative Shell split:

- :func:`persist_review_summary` — the **pure** helper. Takes an
  :class:`AsyncSession` and the agent's :class:`ReviewResult`, returns
  the persisted :class:`ReviewSummary` row. No DBOS.
- :func:`persist_review_summary_tx` — the **DBOS-wrapped**
  transaction. Acquires the DBOS datasource session, calls the pure
  helper, and returns the summary id.
"""

from __future__ import annotations

import logging
from uuid import UUID

from app.core.db import dbos_datasource
from app.models.enums import ReviewVerdict
from app.models.review_summary import ReviewSummary
from app.services.agent.models import ReviewResult
from sqlalchemy.ext.asyncio import AsyncSession

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


@dbos_datasource.transaction()
async def persist_review_summary_tx(
    *,
    pr_id: str,
    commit_id: str,
    result: ReviewResult,
) -> UUID:
    """Durable DBOS transaction: persist the review summary row.

    Returns the ``summary.id`` so the workflow can carry it across
    the step boundary.
    """
    session = dbos_datasource.sql_session()
    summary = await persist_review_summary(
        session,
        pr_id=pr_id,
        commit_id=commit_id,
        result=result,
    )
    return summary.id


__all__ = ["persist_review_summary", "persist_review_summary_tx"]
