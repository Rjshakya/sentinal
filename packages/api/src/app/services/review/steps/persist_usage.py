"""Persist the per-PR review token-usage row.

Two layers, following the Functional Core / Imperative Shell split:

- :func:`sum_total_usages` — pure aggregator. Collapses the per-model
  :class:`app.services.review.workflow_types.TotalUsagesPerPR` envelope
  into a single ``(input_tokens, output_tokens, total_tokens,
  input_token_details)`` tuple the DB row can carry.
- :func:`persist_review_usage` — the **pure** helper. Takes an
  :class:`AsyncSession` and the per-run fields, returns the
  persisted :class:`ReviewUsage` row. No DBOS.
- :func:`persist_review_usage_tx` — the **DBOS-wrapped** transaction.
  Acquires the DBOS datasource session, calls the pure helper, and
  returns the new row's id.
"""

from __future__ import annotations

import logging
from uuid import UUID

from app.core.db import dbos_datasource
from app.models.enums import ReviewRunStatus
from app.models.review_usage import ReviewUsage
from app.services.review.workflow_types import InputTokenDetails, TotalUsagesPerPR
from sqlalchemy.ext.asyncio import AsyncSession

log = logging.getLogger(__name__)


def sum_total_usages(
    usages_per_pr: TotalUsagesPerPR,
) -> tuple[int, int, int, dict[str, int | None]]:
    """Collapse the per-model usages envelope into one row's worth of fields.

    Returns ``(input_tokens, output_tokens, total_tokens,
    input_token_details)``. The ``input_token_details`` is itself a
    flat dict with ``cache_read`` and ``cache_creation`` summed
    across all models in the envelope. Each cache field defaults to
    ``0`` when the underlying provider did not surface that value;
    the final dict always has both keys (never ``None``) so the
    JSONB column never has to special-case missing keys.
    """
    input_tokens = 0
    output_tokens = 0
    total_tokens = 0
    cache_read = 0
    cache_creation = 0

    for model_usage in usages_per_pr["usages"].values():
        input_tokens += model_usage["input_tokens"]
        output_tokens += model_usage["output_tokens"]
        total_tokens += model_usage["total_tokens"]
        details: InputTokenDetails = model_usage.get("input_token_details", {})
        model_cache_read = details.get("cache_read")
        model_cache_creation = details.get("cache_creation")
        if model_cache_read is not None:
            cache_read += model_cache_read
        if model_cache_creation is not None:
            cache_creation += model_cache_creation

    return (
        input_tokens,
        output_tokens,
        total_tokens,
        {"cache_read": cache_read, "cache_creation": cache_creation},
    )


async def persist_review_usage(
    session: AsyncSession,
    *,
    pr_id: str,
    user_id: str,
    pr_number: int,
    repo_id: str,
    review_summary_id: UUID | None,
    review_status: ReviewRunStatus,
    input_tokens: int,
    output_tokens: int,
    total_tokens: int,
    input_token_details: dict[str, int | None] | None,
) -> ReviewUsage:
    """Insert a single :class:`ReviewUsage` row."""
    row = ReviewUsage(
        pr_id=pr_id,
        user_id=user_id,
        pr_number=pr_number,
        repo_id=repo_id,
        review_summary_id=review_summary_id,
        review_status=review_status,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        input_token_details=input_token_details,
    )
    session.add(row)
    await session.flush()
    await session.refresh(row)
    log.info(
        "persisted review usage: usage_id=%s pr_id=%s status=%s "
        "input=%d output=%d total=%d",
        row.id,
        pr_id,
        review_status.value,
        input_tokens,
        output_tokens,
        total_tokens,
    )
    return row


@dbos_datasource.transaction()
async def persist_review_usage_tx(
    *,
    pr_id: str,
    user_id: str,
    pr_number: int,
    repo_id: str,
    review_summary_id: UUID | None,
    review_status: ReviewRunStatus,
    input_tokens: int,
    output_tokens: int,
    total_tokens: int,
    input_token_details: dict[str, int | None] | None,
) -> str:
    """Durable DBOS transaction: persist the review usage row.

    Returns the new row's id as ``str`` so the workflow can carry it
    across the step boundary if it ever needs to (currently it does
    not — the row's existence is the contract).
    """
    session = dbos_datasource.sql_session()
    row = await persist_review_usage(
        session,
        pr_id=pr_id,
        user_id=user_id,
        pr_number=pr_number,
        repo_id=repo_id,
        review_summary_id=review_summary_id,
        review_status=review_status,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        input_token_details=input_token_details,
    )
    return str(row.id)


__all__ = [
    "persist_review_usage",
    "persist_review_usage_tx",
    "sum_total_usages",
]
