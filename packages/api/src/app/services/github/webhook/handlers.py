"""Concrete webhook event handlers.

Every handler takes the :class:`WebhookCtx` and an :class:`AsyncSession`
(caller-owned, per the I/O-at-the-edge convention), mutates the ctx's
outcome fields (``accepted`` / ``skipReason``), and returns ``None``;
the session is ignored by the delegation handlers — the adapters they
call own their own sessions.

Two families:

- **Mirror handlers** (``installation`` / ``installation_repositories``)
  — the local-DB bookkeeping for events the install-flow setup callback
  does not cover.
- **Delegation handlers** (``pull_request`` / ``issue_comment`` /
  ``push``) — forward the domain events to the DBOS dispatch adapters.
  ``pull_request`` ``opened`` and ``issue_comment`` ``created`` run the
  refactored review workflow via
  :mod:`app.workflows.review.triggers`; ``push`` keeps the legacy
  incremental-indexing adapter. The adapter imports are **deferred to
  call time**: the adapters pull in the review / indexing pipelines,
  which in turn import :mod:`app.services.github` — a module-level
  import here would cycle through the partially initialized package.

Handlers never raise; malformed payloads record
``skipReason="malformed_installation"`` on the ctx so the ack stays
informative.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlmodel import col
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.installation import Installation
from app.models.repo import Repo
from app.repositories.installation import InstallationRepository
from app.repositories.repo import RepoRepository
from app.services.github.webhook.types import WebhookCtx
from app.utils.util import uuidToStr


def getInstallationId(payload: dict[str, Any]) -> int | None:
    """Return the payload's installation id, or ``None`` when malformed."""
    installation = payload.get("installation") or {}
    gh_id = installation.get("id")
    return gh_id if isinstance(gh_id, int) else None


def getReposFromPayload(payload: dict[str, Any], key: str) -> list[dict[str, Any]]:
    """Pull the repo-object list from ``payload[key]``, dropping malformed entries."""
    raw = payload.get(key) or []
    return [
        r
        for r in raw
        if isinstance(r, dict)
        and isinstance(r.get("id"), int)
        and isinstance(r.get("full_name"), str)
    ]


async def getUserIdByInstallationId(
    session: AsyncSession, github_installation_id: int
) -> str | None:
    """Return the WorkOS ``user_id`` that owns the local installation row."""
    row = await InstallationRepository(
        session=session
    ).find_by_github_installation_id(github_installation_id)
    return row.user_id if row is not None else None


async def _upsertRepo(
    session: AsyncSession, *, user_id: str, repoPayload: dict[str, Any]
) -> str:
    """Insert-or-fetch a Repo row for one GitHub repo object. Returns repo.id."""
    github_repo_id = repoPayload["id"]
    full_name = repoPayload["full_name"]
    owner, _, name = full_name.partition("/")

    repo = RepoRepository(session=session)
    existing = await repo.find_by_github_repo_id(github_repo_id)
    if existing is not None:
        return existing.id

    row = Repo(
        id=uuidToStr(),
        user_id=user_id,
        github_repo_id=github_repo_id,
        repo_name=name,
        repo_owner=owner,
        clone_url=repoPayload.get("clone_url") or f"https://github.com/{full_name}.git",
        url=repoPayload.get("html_url"),
        private=repoPayload.get("private", False),
        default_branch=repoPayload.get("default_branch"),
    )
    await repo.add(row)
    await session.flush()
    return row.id


# --------------------------------------------------------------------------- #
# installation mirror handlers                                                 #
# --------------------------------------------------------------------------- #


async def handleInstallationDeleted(ctx: WebhookCtx, session: AsyncSession):
    """Delete the local ``installations`` rows for the delivery."""
    gh_id = getInstallationId(ctx.payload)
    if gh_id is None:
        ctx.skipReason = "malformed_installation"
        return None

    repo = InstallationRepository(session=session)
    await repo.delete(col(Installation.github_installation_id) == gh_id)
    await session.commit()
    ctx.accepted = True
    return None


async def _set_suspended(
    session: AsyncSession,
    *,
    github_installation_id: int,
    suspended: bool,
) -> None:
    """Set or clear ``suspended_at`` on the installation row and commit."""
    now = datetime.now(UTC)
    repo = InstallationRepository(session=session)
    row = await repo.find_by_github_installation_id(github_installation_id)
    if row is not None:
        row.suspended_at = now if suspended else None
        row.updated_at = now
    await session.commit()


async def handleInstallationSuspended(ctx: WebhookCtx, session: AsyncSession):
    """Mark the local ``installations`` rows as suspended."""
    gh_id = getInstallationId(ctx.payload)
    if gh_id is None:
        ctx.skipReason = "malformed_installation"
        return None

    await _set_suspended(session, github_installation_id=gh_id, suspended=True)
    ctx.accepted = True
    return None


async def handleInstallationUnsuspended(ctx: WebhookCtx, session: AsyncSession):
    """Clear the ``suspended_at`` flag on the local ``installations`` rows."""
    gh_id = getInstallationId(ctx.payload)
    if gh_id is None:
        ctx.skipReason = "malformed_installation"
        return None

    await _set_suspended(session, github_installation_id=gh_id, suspended=False)
    ctx.accepted = True
    return None


# --------------------------------------------------------------------------- #
# installation_repositories mirror handlers                                    #
# --------------------------------------------------------------------------- #


async def handleInstallationReposAdded(ctx: WebhookCtx, session: AsyncSession):
    """Upsert one :class:`Repo` row per added repo for the installation owner."""
    gh_id = getInstallationId(ctx.payload)
    if gh_id is None:
        ctx.skipReason = "malformed_installation"
        return None

    repositories = getReposFromPayload(ctx.payload, "repositories_added")
    if not repositories:
        ctx.accepted = True
        return None

    user_id = await getUserIdByInstallationId(session, gh_id)
    if user_id is None:
        ctx.skipReason = "unowned_installation"
        return None

    for repoPayload in repositories:
        await _upsertRepo(session, user_id=user_id, repoPayload=repoPayload)
    await session.commit()
    ctx.accepted = True
    return None


async def handleInstallationReposRemoved(ctx: WebhookCtx, session: AsyncSession):
    """Delete the local :class:`Repo` rows matching the removed repos."""
    gh_id = getInstallationId(ctx.payload)
    if gh_id is None:
        ctx.skipReason = "malformed_installation"
        return None

    removed = getReposFromPayload(ctx.payload, "repositories_removed")
    if not removed:
        ctx.accepted = True
        return None

    github_repo_ids = {r["id"] for r in removed}
    repo = RepoRepository(session=session)
    await repo.delete(col(Repo.github_repo_id).in_(github_repo_ids))
    await session.commit()
    ctx.accepted = True
    return None


# --------------------------------------------------------------------------- #
# delegation handlers                                                          #
# --------------------------------------------------------------------------- #


async def handlePullRequestOpened(ctx: WebhookCtx, session: AsyncSession):
    """Forward a ``pull_request`` ``opened`` delivery to the review trigger."""
    from app.workflows.review.triggers import handlePullRequestOpened as trigger

    ack = await trigger(
        payload=ctx.payload,
        delivery=ctx.delivery,
        session=session,
    )
    ctx.accepted = ack.accepted
    ctx.skipReason = ack.skip_reason
    return None


async def handleIssueCommentCreated(ctx: WebhookCtx, session: AsyncSession):
    """Forward an ``issue_comment`` ``created`` delivery to the review trigger."""
    from app.workflows.review.triggers import handleIssueCommentCreated as trigger

    ack = await trigger(ctx.payload, ctx.delivery, session)
    ctx.accepted = ack.accepted
    ctx.skipReason = ack.skip_reason
    return None


async def handlePush(ctx: WebhookCtx, session: AsyncSession):
    """Forward a ``push`` delivery to the incremental-indexing adapter."""
    from app.services.indexing.incremental import handle_push_event

    ack = await handle_push_event(ctx.payload, ctx.delivery)
    ctx.accepted = ack.accepted
    ctx.skipReason = ack.skip_reason

    return None


__all__ = [
    "handleInstallationDeleted",
    "handleInstallationReposAdded",
    "handleInstallationReposRemoved",
    "handleInstallationSuspended",
    "handleInstallationUnsuspended",
    "handleIssueCommentCreated",
    "handlePullRequestOpened",
    "handlePush",
]
