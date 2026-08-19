"""DBOS steps that record the review workflow's lifecycle onto the
``review`` table.

Three steps — one per state transition, plus a pure error-context
helper:

- :func:`mark_review_is_running_step` — finds (or creates) the
  ``review`` row for the current workflow and flips it to ``RUNNING``:
  records the pr link, sandbox, and the LLM snapshot.
- :func:`mark_review_is_stopped_step` — flips to ``SUCCESS`` with the
  surviving comment count, the GitHub review id (when the post
  workflow returned one), and ``completed_at``.
- :func:`mark_review_is_errored_step` — flips to ``FAILED`` with the
  typed error name / message / context and ``completed_at``.
- :func:`build_error_context` — pure; projects an exception onto the
  ``error_context`` JSONB shape.

Every step is durable: each is ``@DBOS.step(retries_allowed=True,
max_attempts=3, should_retry=_SHOULD_RETRY_TRANSIENT)`` and raises
:class:`app.services.review.errors.ReviewRunUpdateError` on failure,
so a DB blip is retried and a persistent failure surfaces as a
workflow ERROR instead of silently leaving the row stuck in
``RUNNING``. The running step's find-or-create semantics make retries
safe (a retried insert re-finds the committed row via the unique
``workflow_id``). Only :func:`mark_review_is_errored_step` still
accepts a ``None`` review id (it runs from the workflow's ``except``
block, where the running step may never have completed) and no-ops in
that case.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from dbos import DBOS
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.core.db import async_session_maker
from app.models.review import Review, ReviewState
from app.services.review._internal import _SHOULD_RETRY_TRANSIENT
from app.services.review.errors import (
    ReviewAgentsInvocationError,
    ReviewRunUpdateError,
)

log = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(UTC)


async def _fetch_review(session: AsyncSession, review_id: str) -> Review | None:
    return await session.get(Review, review_id)


@DBOS.step(
    retries_allowed=True,
    max_attempts=3,
    should_retry=_SHOULD_RETRY_TRANSIENT,
)
async def mark_review_is_running_step(
    *,
    user_id: str,
    repo_id: str,
    gh_repo_id: int,
    pr_id: str,
    pr_number: int,
    commit_id: str,
    base_sha: str | None,
    trigger: str,
    sandbox_id: str,
    workflow_id: str,
    llm_provider: str,
    llm_model: str,
    llm_base_url: str | None,
) -> str:
    """Find-or-create the ``RUNNING`` row for the current workflow.

    Uses ``workflow_id`` as the deterministic DBOS id so the row is
    unique per run and duplicate dispatches / workflow restarts reuse
    it. On restart the existing row is reset to ``RUNNING`` and its
    error fields cleared (``started_at`` is kept from the original
    attempt). Returns the row's ``id`` so the workflow can carry it
    across step boundaries.

    Raises:
        ReviewRunUpdateError: the row could not be written (or the
            existing row could not be reset). Transient — DBOS retries
            the step up to 3 attempts, then the workflow is ERROR.
    """
    try:
        async with async_session_maker() as session:
            existing = (
                await session.exec(
                    select(Review).where(Review.workflow_id == workflow_id)
                )
            ).first()

            if existing is not None:
                existing.state = ReviewState.RUNNING
                existing.pr_id = pr_id
                existing.sandbox_id = sandbox_id
                existing.llm_provider = llm_provider
                existing.llm_model = llm_model
                existing.llm_base_url = llm_base_url
                existing.error_name = None
                existing.error_message = None
                existing.error_context = None

                if existing.started_at is None:
                    existing.started_at = _utcnow()
                    existing.updated_at = _utcnow()

                await session.commit()

                log.info(
                    "mark_review_is_running_step: reset existing row "
                    "review_id=%s workflow_id=%s",
                    existing.id,
                    workflow_id,
                )

                return existing.id

            review = Review(
                user_id=user_id,
                repo_id=repo_id,
                gh_repo_id=gh_repo_id,
                pr_id=pr_id,
                pr_number=pr_number,
                commit_id=commit_id,
                base_sha=base_sha,
                workflow_id=workflow_id,
                trigger=trigger,
                state=ReviewState.RUNNING,
                sandbox_id=sandbox_id,
                llm_provider=llm_provider,
                llm_model=llm_model,
                llm_base_url=llm_base_url,
                started_at=_utcnow(),
            )
            session.add(review)
            await session.commit()
            await session.refresh(review)
        log.info(
            "mark_review_is_running_step: ok review_id=%s workflow_id=%s "
            "repo_id=%s pr_number=%s",
            review.id,
            workflow_id,
            repo_id,
            pr_number,
        )
        return review.id
    except Exception as exc:
        log.warning(
            "mark_review_is_running_step: failed workflow_id=%s repo_id=%s "
            "pr_number=%s",
            workflow_id,
            repo_id,
            pr_number,
            exc_info=True,
        )
        raise ReviewRunUpdateError(
            f"mark running failed for workflow_id={workflow_id} "
            f"repo_id={repo_id} pr_number={pr_number}: {exc}"
        ) from exc


@DBOS.step(
    retries_allowed=True,
    max_attempts=3,
    should_retry=_SHOULD_RETRY_TRANSIENT,
)
async def mark_review_is_stopped_step(
    *,
    review_id: str,
    comment_count: int,
    github_review_id: str | None,
) -> None:
    """Flip the row to ``SUCCESS`` and persist the run outcome.

    Raises:
        ReviewRunUpdateError: the row does not exist or could not be
            updated. Transient — DBOS retries up to 3 attempts, then
            the workflow lands in the ``except`` block, which flips
            the row to ``FAILED`` with this error and re-raises.
    """
    try:
        async with async_session_maker() as session:
            review = await _fetch_review(session, review_id)
            if review is None:
                raise ReviewRunUpdateError(
                    f"mark stopped: review {review_id!r} not found"
                )
            review.state = ReviewState.SUCCESS
            review.comment_count = comment_count
            review.github_review_id = github_review_id
            review.completed_at = _utcnow()
            review.updated_at = _utcnow()
            await session.commit()
        log.info(
            "mark_review_is_stopped_step: ok review_id=%s comments=%d "
            "github_review_id=%s",
            review_id,
            comment_count,
            github_review_id,
        )
    except Exception as exc:
        log.warning(
            "mark_review_is_stopped_step: failed review_id=%s",
            review_id,
            exc_info=True,
        )
        raise ReviewRunUpdateError(
            f"mark stopped failed for review_id={review_id}: {exc}"
        ) from exc


@DBOS.step(
    retries_allowed=True,
    max_attempts=3,
    should_retry=_SHOULD_RETRY_TRANSIENT,
)
async def mark_review_is_errored_step(
    *,
    review_id: str | None,
    error_name: str,
    error_message: str,
    error_context: dict[str, Any] | None,
) -> None:
    """Flip the row to ``FAILED`` and persist the typed error info.

    No-ops when ``review_id`` is ``None`` — the workflow's ``except``
    block calls this even when the running step never completed, so
    there may be no row to flip. The workflow wraps this call in its
    own try/except so a failure here never masks the original error.

    Raises:
        ReviewRunUpdateError: the row does not exist or could not be
            updated. Transient — DBOS retries up to 3 attempts.
    """
    if review_id is None:
        return
    try:
        async with async_session_maker() as session:
            review = await _fetch_review(session, review_id)
            if review is None:
                raise ReviewRunUpdateError(
                    f"mark errored: review {review_id!r} not found"
                )
            review.state = ReviewState.FAILED
            review.error_name = error_name
            review.error_message = error_message
            review.error_context = error_context
            review.completed_at = _utcnow()
            review.updated_at = _utcnow()
            await session.commit()
        log.info(
            "mark_review_is_errored_step: ok review_id=%s error=%s",
            review_id,
            error_name,
        )
    except Exception as exc:
        log.warning(
            "mark_review_is_errored_step: failed review_id=%s",
            review_id,
            exc_info=True,
        )
        raise ReviewRunUpdateError(
            f"mark errored failed for review_id={review_id}: {exc}"
        ) from exc


def build_error_context(exc: BaseException) -> dict[str, Any] | None:
    """Project an exception onto the ``error_context`` JSONB shape.

    Full payload for :class:`ReviewAgentsInvocationError` (the
    dominant failure mode — both agent lanes exhausted their
    retries); ``None`` for everything else (the row keeps just
    ``error_name`` / ``error_message``).

    ``error_name`` carries the per-agent error class names of the
    failed lanes (e.g. ``"SummaryAgentInvocationError,
    CommentsAgentInvocationError"``), falling back to the aggregate
    class name when no lane detail is available.
    """
    if isinstance(exc, ReviewAgentsInvocationError):
        failed_names = [type(e).__name__ for e in exc.failed_agents]
        return {
            "error_name": ", ".join(failed_names) or type(exc).__name__,
            "succeeded_agents": list(exc.succeeded_agents),
            "llm_provider": exc.llm_provider,
            "llm_model": exc.llm_model,
            "occurred_at": exc.occurred_at.isoformat(),
        }
    return None


__all__ = [
    "build_error_context",
    "mark_review_is_errored_step",
    "mark_review_is_running_step",
    "mark_review_is_stopped_step",
]
