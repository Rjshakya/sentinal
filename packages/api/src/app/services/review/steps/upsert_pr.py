"""Upsert the pull-request row during a review.

Two layers, following the Functional Core / Imperative Shell split:

- :func:`upsert_pull_request` — the **pure** helper. Takes a
  :class:`AsyncSession` and the PR fields, returns the persisted
  :class:`PullRequest` row. No DBOS, no workflow boundary.
- :func:`upsert_pull_request_tx` — the **DBOS-wrapped** transaction.
  Acquires the DBOS datasource session, calls the pure helper, and
  returns the ``pr.id`` so the workflow can carry it forward.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlmodel import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import dbos_datasource
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


@dbos_datasource.transaction()
async def upsert_pull_request_tx(
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
) -> str:
    """Durable DBOS transaction: insert or update the :class:`PullRequest` row.

    Returns the ``pr.id`` so the workflow can carry it across the
    step boundary.
    """
    session = dbos_datasource.sql_session()
    pr = await upsert_pull_request(
        session,
        repo_id=repo_id,
        github_pr_id=github_pr_id,
        number=number,
        base_branch=base_branch,
        base_sha=base_sha,
        head_branch=head_branch,
        head_sha=head_sha,
        title=title,
        body=body,
        author=author,
        status=status,
    )
    return pr.id


__all__ = ["upsert_pull_request", "upsert_pull_request_tx"]
