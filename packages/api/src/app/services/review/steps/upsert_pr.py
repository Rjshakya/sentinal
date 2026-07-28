"""Upsert the pull-request row during a review."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlmodel import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import PRStatus
from app.models.pull_request import PullRequest
from app.utils.util import uuidToStr
log = logging.getLogger(__name__)


async def upsert_pull_request(
    session: AsyncSession,
    *,
    repo_id: str,
    github_pr_id: int,
    number: int,
    base_branch: str,
    base_sha: str,
    head_branch: str,
    head_sha: str,
    title: str,
    body: str,
    author: str,
    status: PRStatus,
) -> PullRequest:
    """Insert or update a :class:`PullRequest` row keyed on
    ``(repo_id, number)``.

    On update, the SHAs and branches are refreshed. On insert, the
    author / title / body are left empty — the webhook is the source of
    truth for those, and the orchestrator only needs the SHAs and
    branches to do its work.
    """
    existing = (
        await session.execute(
            select(PullRequest).where(
                PullRequest.repo_id == repo_id,
                PullRequest.number == number,
            )
        )
    ).scalars().first()

    now = datetime.now(UTC)
    if existing is not None:
        existing.base_branch = base_branch
        existing.base_sha = base_sha
        existing.head_branch = head_branch
        existing.head_sha = head_sha
        existing.updated_at = now
        existing.title = title
        existing.body = body
        existing.author = author
        existing.status = status
        session.add(existing)
        await session.flush()
        log.info(
            "updated pull request: pr_id=%s repo_id=%s number=%s",
            existing.id,
            repo_id,
            number,
        )
        return existing

    pr = PullRequest(
        id=uuidToStr(),
        repo_id=repo_id,
        number=number,
        author=author,
        title=title,
        body=body,
        status=status,
        base_branch=base_branch,
        base_sha=base_sha,
        head_branch=head_branch,
        head_sha=head_sha,
    )
    session.add(pr)
    await session.flush()
    await session.refresh(pr)
    log.info(
        "inserted pull request: pr_id=%s repo_id=%s number=%s github_pr_id=%s",
        pr.id,
        repo_id,
        number,
        github_pr_id,
    )
    return pr


__all__: list[str] = ["upsert_pull_request"]
