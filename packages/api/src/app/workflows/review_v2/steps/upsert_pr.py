"""Upsert the pull-request row during a review.

Insert or update keyed on ``(repo_id, number)``: on update the SHAs,
branches, and PR metadata are refreshed; on insert a fresh row is
created. Returns the row's id.
"""

from __future__ import annotations

from datetime import UTC, datetime

from app.core.db import async_session_maker
from app.models.pull_request import PullRequest
from app.repositories.pull_request import PullRequestRepository
from app.utils.branded import PrRowId, RepoId
from app.utils.util import uuidToStr
from app.workflows.review_v2.errors import ReviewStepFailure, UpsertPRError
from app.workflows.review_v2.types import ReviewWorkflowInput


async def upsertPullRequestTx(
    *,
    repoId: RepoId,
    input: ReviewWorkflowInput,
) -> PrRowId:
    """Insert or update the :class:`PullRequest` row; returns its id.

    Raises:
        ReviewStepFailure: the row could not be written.
    """
    try:
        async with async_session_maker() as session:
            repo = PullRequestRepository(session=session)
            existing = await repo.find_by_repo_and_number(repoId, input.prNumber)
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
        raise ReviewStepFailure(
            UpsertPRError(
                message=f"failed to upsert pull request: {type(exc).__name__}: {exc}",
                userId=input.userId,
                repoId=repoId,
                prNumber=input.prNumber,
                headSha=input.headSha,
            )
        ) from exc


__all__ = ["upsertPullRequestTx"]
