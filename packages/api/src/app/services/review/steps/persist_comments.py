"""Persist the code-comment rows produced by the review agent."""

from __future__ import annotations

import logging
from collections.abc import Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.code_comment import CodeComment
from app.services.agent.models import CodeCommentDraft
from app.services.review.helpers import map_drafts_to_comment_rows

log = logging.getLogger(__name__)


async def persist_code_comments(
    session: AsyncSession,
    *,
    pr_id: str,
    commit_id: str,
    comments: Sequence[CodeCommentDraft],
) -> list[CodeComment]:
    """Insert one :class:`CodeComment` row per draft finding."""
    rows = map_drafts_to_comment_rows(
        pr_id=pr_id, commit_id=commit_id, comments=comments
    )

    if not rows:
        log.info("no code comments to persist (pr_id=%s)", pr_id)
        return []

    session.add_all(rows)
    await session.flush()
    for row in rows:
        await session.refresh(row)

    log.info(
        "persisted %d code comment(s): pr_id=%s commit_id=%s",
        len(rows),
        pr_id,
        commit_id,
    )
    return rows


__all__: list[str] = ["persist_code_comments"]
