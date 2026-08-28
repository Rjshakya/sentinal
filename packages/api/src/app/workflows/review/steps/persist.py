"""Persist the review summary, code comments, and token-usage rows.

One value-returning helper per table (plus the pure draft→row mapper
and the usage aggregator), each paired with a **DBOS-wrapped**
transaction edge that raises :class:`ReviewStepFailure` on failure.

- :func:`mapDraftsToCommentRows` — pure; translates
  :class:`CodeCommentDraft` objects into ORM rows (severity / side
  strings coerced into the enums; a bad value raises ``ValueError`` —
  a programmer error, not a pipeline failure mode).
- :func:`sumTotalUsages` — pure; collapses the per-model usage
  envelope into one row's worth of fields.
- :func:`persistReviewSummary` / :func:`persistCodeComments` /
  :func:`persistReviewUsage` — the value-returning workers.
- :func:`persistReviewSummaryTx` / :func:`persistCodeCommentsTx` /
  :func:`persistReviewUsageTx` — the durable transaction edges.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import dbos_datasource
from app.models.code_comment import CodeComment
from app.models.enums import (
    CommentSeverity,
    CommentSide,
    CommentState,
    ReviewRunStatus,
    ReviewVerdict,
)
from app.models.review_summary import ReviewSummary
from app.models.review_usage import ReviewUsage
from app.utils.branded import (
    CommitId,
    PRNumber,
    PrRowId,
    RepoId,
    ReviewRowId,
    UserId,
)
from app.utils.schema import CodeCommentDraft, ReviewResult
from app.utils.util import uuidToStr
from app.workflows.review.errors import PersistError, ReviewStepFailure
from app.workflows.review.types import InputTokenDetails, TotalUsagesPerPR

log = logging.getLogger(__name__)


def mapDraftsToCommentRows(
    *,
    prRowId: PrRowId,
    reviewRowId: ReviewRowId | None,
    commitId: CommitId,
    comments: Sequence[CodeCommentDraft],
) -> list[CodeComment]:
    """Translate :class:`CodeCommentDraft` objects into ORM rows.

    Each draft becomes a :class:`CodeComment` keyed to
    ``(pr_id, commit_id)`` with ``state=ACTIVE`` and the run's
    ``review_id`` when one exists.
    """
    rows: list[CodeComment] = []
    for draft in comments:
        rows.append(
            CodeComment(
                id=uuidToStr(),
                pr_id=prRowId,
                review_id=reviewRowId,
                commit_id=commitId,
                file_name=draft.file_name,
                comment=draft.comment,
                severity=CommentSeverity(draft.severity),
                from_line=draft.from_line,
                to_line=draft.to_line,
                side=CommentSide(draft.side),
                node_type=draft.node_type,
                state=CommentState.ACTIVE,
            )
        )
    return rows


def sumTotalUsages(
    usagesPerPr: TotalUsagesPerPR,
) -> tuple[int, int, int, dict[str, int | None]]:
    """Collapse the per-model usages envelope into one row's worth of fields.

    Returns ``(input_tokens, output_tokens, total_tokens,
    input_token_details)``. The cache fields default to ``0`` when the
    provider did not surface them, so the JSONB column never has to
    special-case missing keys.
    """
    input_tokens = 0
    output_tokens = 0
    total_tokens = 0
    cache_read = 0
    cache_creation = 0

    for model_usage in usagesPerPr["usages"].values():
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


async def persistReviewSummary(
    session: AsyncSession,
    *,
    prRowId: PrRowId,
    reviewRowId: ReviewRowId | None,
    commitId: CommitId,
    review: ReviewResult,
) -> UUID | PersistError:
    """Insert a single :class:`ReviewSummary` row; returns its id."""
    try:
        summary = ReviewSummary(
            pr_id=prRowId,
            review_id=reviewRowId,
            commit_id=commitId,
            summary=review.summary,
            verdict=ReviewVerdict(review.verdict),
        )
        session.add(summary)
        await session.flush()
        await session.refresh(summary)
        return summary.id
    except Exception as exc:
        return PersistError(
            message=f"failed to persist review summary: {type(exc).__name__}: {exc}"
        )


async def persistCodeComments(
    session: AsyncSession,
    *,
    prRowId: PrRowId,
    reviewRowId: ReviewRowId | None,
    commitId: CommitId,
    comments: Sequence[CodeCommentDraft],
) -> list[str] | PersistError:
    """Insert one :class:`CodeComment` row per draft; returns row ids."""
    try:
        rows = mapDraftsToCommentRows(
            prRowId=prRowId,
            reviewRowId=reviewRowId,
            commitId=commitId,
            comments=comments,
        )
        if not rows:
            return []
        session.add_all(rows)
        await session.flush()
        for row in rows:
            await session.refresh(row)
        return [row.id for row in rows]
    except Exception as exc:
        return PersistError(
            message=f"failed to persist code comments: {type(exc).__name__}: {exc}"
        )


async def persistReviewUsage(
    session: AsyncSession,
    *,
    userId: UserId,
    prRowId: PrRowId,
    prNumber: PRNumber,
    repoId: RepoId,
    reviewRowId: ReviewRowId | None,
    reviewSummaryId: UUID | None,
    inputTokens: int,
    outputTokens: int,
    totalTokens: int,
    inputTokenDetails: dict[str, int | None] | None,
    llmModelId: str | None,
    llmProvider: str | None,
    llmBaseUrl: str | None,
) -> str | PersistError:
    """Insert a single :class:`ReviewUsage` row; returns its id."""
    try:
        row = ReviewUsage(
            pr_id=prRowId,
            review_id=reviewRowId,
            user_id=userId,
            pr_number=prNumber,
            repo_id=repoId,
            review_summary_id=reviewSummaryId,
            review_status=ReviewRunStatus.SUCCESS,
            input_tokens=inputTokens,
            output_tokens=outputTokens,
            total_tokens=totalTokens,
            input_token_details=inputTokenDetails,
            llm_model_id=llmModelId,
            llm_provider=llmProvider,
            llm_base_url=llmBaseUrl,
        )
        session.add(row)
        await session.flush()
        await session.refresh(row)
        return row.id
    except Exception as exc:
        return PersistError(
            message=f"failed to persist review usage: {type(exc).__name__}: {exc}",
            userId=userId,
            repoId=repoId,
            prNumber=prNumber,
        )


@dbos_datasource.transaction()
async def persistReviewSummaryTx(
    *,
    prRowId: PrRowId,
    reviewRowId: ReviewRowId | None,
    commitId: CommitId,
    review: ReviewResult,
) -> UUID:
    """Durable DBOS transaction: persist the review summary row.

    Raises:
        ReviewStepFailure: the row could not be written (wrapping a
            :class:`PersistError`).
    """
    session = dbos_datasource.sql_session()
    result = await persistReviewSummary(
        session,
        prRowId=prRowId,
        reviewRowId=reviewRowId,
        commitId=commitId,
        review=review,
    )
    if isinstance(result, PersistError):
        raise ReviewStepFailure(result)
    return result


@dbos_datasource.transaction()
async def persistCodeCommentsTx(
    *,
    prRowId: PrRowId,
    reviewRowId: ReviewRowId | None,
    commitId: CommitId,
    comments: Sequence[CodeCommentDraft],
) -> list[str]:
    """Durable DBOS transaction: persist the code-comment rows.

    Raises:
        ReviewStepFailure: a row could not be written (wrapping a
            :class:`PersistError`).
    """
    session = dbos_datasource.sql_session()
    result = await persistCodeComments(
        session,
        prRowId=prRowId,
        reviewRowId=reviewRowId,
        commitId=commitId,
        comments=comments,
    )
    if isinstance(result, PersistError):
        raise ReviewStepFailure(result)
    return result


@dbos_datasource.transaction()
async def persistReviewUsageTx(
    *,
    userId: UserId,
    prRowId: PrRowId,
    prNumber: PRNumber,
    repoId: RepoId,
    reviewRowId: ReviewRowId | None,
    reviewSummaryId: UUID | None,
    inputTokens: int,
    outputTokens: int,
    totalTokens: int,
    inputTokenDetails: dict[str, int | None] | None,
    llmModelId: str | None,
    llmProvider: str | None,
    llmBaseUrl: str | None,
) -> str:
    """Durable DBOS transaction: persist the review-usage row.

    Raises:
        ReviewStepFailure: the row could not be written (wrapping a
            :class:`PersistError`).
    """
    session = dbos_datasource.sql_session()
    result = await persistReviewUsage(
        session,
        userId=userId,
        prRowId=prRowId,
        prNumber=prNumber,
        repoId=repoId,
        reviewRowId=reviewRowId,
        reviewSummaryId=reviewSummaryId,
        inputTokens=inputTokens,
        outputTokens=outputTokens,
        totalTokens=totalTokens,
        inputTokenDetails=inputTokenDetails,
        llmModelId=llmModelId,
        llmProvider=llmProvider,
        llmBaseUrl=llmBaseUrl,
    )
    if isinstance(result, PersistError):
        raise ReviewStepFailure(result)
    return result


__all__ = [
    "mapDraftsToCommentRows",
    "persistCodeComments",
    "persistCodeCommentsTx",
    "persistReviewSummary",
    "persistReviewSummaryTx",
    "persistReviewUsage",
    "persistReviewUsageTx",
    "sumTotalUsages",
]