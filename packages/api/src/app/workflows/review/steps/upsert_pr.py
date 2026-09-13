"""Upsert the pull-request row during a review.

Two layers:

- :func:`upsertPullRequest` — the value-returning helper. Takes the
  caller's :class:`AsyncSession` and the PR fields, returns the
  persisted row id or a :class:`UpsertPRError` value.
- :func:`upsertPullRequestTx` — the **DBOS-wrapped** transaction edge.
  Acquires the DBOS datasource session, calls the pure helper, and
  raises :class:`ReviewStepFailure` on failure.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from dbos import DBOS
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.db import async_session_maker
from app.models.enums import PRStatus
from app.models.pull_request import PullRequest
from app.repositories.pull_request import PullRequestRepository
from app.utils.branded import PrRowId, RepoId
from app.utils.util import uuidToStr
from app.workflows.review.errors import ReviewStepFailure, UpsertPRError
from app.workflows.review.types import ReviewWorkflowInput

log = logging.getLogger(__name__)


async def upsertPullRequest(
    session: AsyncSession,
    *,
    repoId: RepoId,
    input: ReviewWorkflowInput,
) -> PrRowId | UpsertPRError:
    """Insert or update a :class:`PullRequest` row keyed on
    ``(repo_id, number)``.

    On update the SHAs, branches, and PR metadata are refreshed; on
    insert a fresh row is created. Returns the row's id.
    """
    repo = PullRequestRepository(session=session)
    existing = await repo.find_by_repo_and_number(repoId, input.prNumber)

    try:
        if existing is not None:
            existing.base_branch = input.baseBranch
            existing.base_sha = input.baseSha
            existing.head_branch = input.headBranch
            existing.head_sha = input.headSha
            existing.title = input.title
            existing.body = input.body
            existing.author = input.author
            existing.status = input.status
            existing.updated_at = datetime.now(UTC)
            await repo.add(existing)
            await session.commit()
            return PrRowId(existing.id)

        pr = PullRequest(
            id=uuidToStr(),
            repo_id=repoId,
            number=input.prNumber,
            author=input.author,
            title=input.title,
            body=input.body,
            status=input.status,
            base_branch=input.baseBranch,
            base_sha=input.baseSha,
            head_branch=input.headBranch,
            head_sha=input.headSha,
        )
        await repo.add(pr)
        await session.commit()
        await session.refresh(pr)
        return PrRowId(pr.id)
    except Exception as exc:
        return UpsertPRError(
            message=f"failed to upsert pull request: {type(exc).__name__}: {exc}",
            userId=input.userId,
            repoId=repoId,
            prNumber=input.prNumber,
            headSha=input.headSha,
        )


@DBOS.step()
async def upsertPullRequestTx(
    *,
    repoId: RepoId,
    input: ReviewWorkflowInput,
) -> PrRowId:
    """Durable DBOS transaction: insert or update the :class:`PullRequest` row.

    Raises:
        ReviewStepFailure: the row could not be written (wrapping a
            :class:`UpsertPRError`).
    """
    async with async_session_maker() as session:
        result = await upsertPullRequest(session, repoId=repoId, input=input)
        if isinstance(result, UpsertPRError):
            raise ReviewStepFailure(result)
        return result


__all__ = ["upsertPullRequest", "upsertPullRequestTx"]
