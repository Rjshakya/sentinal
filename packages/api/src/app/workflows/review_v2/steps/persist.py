"""Persist the review summary, code comments, and token-usage rows.

One Tx function per table (each opens its own session and raises
:class:`ReviewStepFailure` on failure), plus the pure draft→row
mapper :func:`mapDraftsToCommentRows` and the usage aggregator
:func:`sumTotalUsages`.
"""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from sqlmodel import col

from app.core.db import async_session_maker
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
from app.repositories.code_comment import CodeCommentRepository
from app.repositories.review_summary import ReviewSummaryRepository
from app.repositories.review_usage import ReviewUsageRepository
from app.utils.branded import (
    CommitId,
    PRNumber,
    PrRowId,
    RepoId,
    ReviewRowId,
    UserId,
)
from app.utils.schema import CodeCommentDraft, ReviewResult
from app.utils.severity_badge import withSeverityBadge
from app.utils.util import uuidToStr
from app.workflows.review_v2.errors import PersistError, ReviewStepFailure
from app.workflows.review_v2.types import InputTokenDetails, TotalUsagesPerPR


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
                comment=withSeverityBadge(draft.severity, draft.comment),
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


def persistError(
    message: str,
    *,
    userId: UserId | None = None,
    repoId: RepoId | None = None,
    prNumber: PRNumber | None = None,
) -> ReviewStepFailure:
    return ReviewStepFailure(
        PersistError(
            message=message,
            userId=userId,
            repoId=repoId,
            prNumber=prNumber,
        )
    )


async def persistReviewSummaryTx(
    *,
    prRowId: PrRowId,
    reviewRowId: ReviewRowId | None,
    commitId: CommitId,
    review: ReviewResult,
) -> UUID:
    """Persist the review summary row; returns its id.

    Raises:
        ReviewStepFailure: the row could not be written.
    """
    try:
        async with async_session_maker() as session:
            repo = ReviewSummaryRepository(session=session)
            # Idempotent retry: a same-run re-insert matches the
            # (review_id) arbiter and refreshes summary/verdict in
            # place. Cross-run same-commit conflicts are deliberately
            # unhandled — production cannot produce them (comment
            # re-runs skip, opened runs dedupe by execution name).
            row = await repo.upsert(
                ReviewSummary(
                    pr_id=prRowId,
                    review_id=reviewRowId,
                    commit_id=commitId,
                    summary=review.summary,
                    verdict=ReviewVerdict(review.verdict),
                ),
                conflict_on=[col(ReviewSummary.review_id)],
            )
            await session.commit()
            await session.refresh(row)
            return row.id
    except Exception as exc:
        raise persistError(
            f"failed to persist review summary: {type(exc).__name__}: {exc}"
        ) from exc


async def persistCodeCommentsTx(
    *,
    prRowId: PrRowId,
    reviewRowId: ReviewRowId | None,
    commitId: CommitId,
    comments: Sequence[CodeCommentDraft],
) -> list[str]:
    """Persist the code-comment rows; returns the row ids.

    Raises:
        ReviewStepFailure: a row could not be written.
    """
    try:
        async with async_session_maker() as session:
            repo = CodeCommentRepository(session=session)
            if reviewRowId is not None:
                # Idempotency: a step retry replays to an identical row
                # set instead of duplicating. Guarded — an unguarded
                # `review_id == None` would compile to IS NULL and wipe
                # unrelated null-review rows.
                await repo.delete(col(CodeComment.review_id) == reviewRowId)
            rows = mapDraftsToCommentRows(
                prRowId=prRowId,
                reviewRowId=reviewRowId,
                commitId=commitId,
                comments=comments,
            )
            if not rows:
                await session.commit()
                return []
            await repo.add_all(rows)
            await session.flush()
            await session.commit()
            return [row.id for row in rows]
    except Exception as exc:
        raise persistError(
            f"failed to persist code comments: {type(exc).__name__}: {exc}"
        ) from exc


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
    """Persist the review-usage row; returns its id.

    Raises:
        ReviewStepFailure: the row could not be written.
    """
    try:
        async with async_session_maker() as session:
            repo = ReviewUsageRepository(session=session)
            if reviewRowId is not None:
                # Same idempotency rationale as comments: retries must
                # not double-count token metrics.
                await repo.delete(col(ReviewUsage.review_id) == reviewRowId)
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
            await repo.add(row)
            await session.flush()
            await session.commit()
            return row.id
    except Exception as exc:
        raise persistError(
            f"failed to persist review usage: {type(exc).__name__}: {exc}",
            userId=userId,
            repoId=repoId,
            prNumber=prNumber,
        ) from exc


__all__ = [
    "mapDraftsToCommentRows",
    "persistCodeCommentsTx",
    "persistError",
    "persistReviewSummaryTx",
    "persistReviewUsageTx",
    "sumTotalUsages",
]
